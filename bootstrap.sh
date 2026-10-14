#!/bin/bash
# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# ==============================================================================
# Creative Studio Infrastructure Bootstrap Script (Resumable)
#
# This interactive script guides a user through the entire process of setting
# up the Creative Studio infrastructure in a new or existing Google Cloud project.
# It saves progress and can be safely restarted if it fails.
# ==============================================================================

set -e

# --- Configuration ---
REQUIRED_TERRAFORM_VERSION="1.14.1"
UPSTREAM_REPO_URL="https://github.com/GoogleCloudPlatform/gcc-creative-studio"
TEMPLATE_ENV_DIR="environments/gv-dev"
DEFAULT_ENV_NAME="gv-dev"
DEFAULT_BRANCH_NAME="main"
GCS_BUCKET_SUFFIX_FORMAT="cstudio-%s-tfstate"
GCS_BUCKET_PREFIX_FORMAT="infra/%s/state"
BE_SERVICE_NAME="cstudio-be"
FE_SERVICE_NAME="cstudio-fe"

# script will automatically set these
AUTO_OAUTH_CLIENT_ID=""            # IAP OAuth Web Client ID (IAP_CLIENT_ID / logout only)

STATE_FILE=""
REPO_ROOT=""

# --- Color Definitions (High Contrast) ---
C_RESET='\033[0m'
C_RED='\033[1;31m'     # Bold/Bright Red for errors
C_GREEN='\033[1;32m'   # Bold/Bright Green for success
C_YELLOW='\033[1;33m'  # Bold/Bright Yellow for warnings and URLs
C_BLUE='\033[1;34m'    # Bold/Bright Blue for steps and prompts
C_CYAN='\033[1;36m'    # Bold/Bright Cyan for general info

# --- Helper Functions ---
info() { echo -e "${C_CYAN}➡️  $1${C_RESET}"; }
prompt() { echo -e "${C_BLUE}🤔  $1${C_RESET}"; }
warn() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }
fail() { echo -e "${C_RED}❌  $1${C_RESET}" >&2; exit 1; }
success() { echo -e "${C_GREEN}✅  $1${C_RESET}"; }
step() { echo -e "\n${C_BLUE}--- Step $1: $2 ---${C_RESET}"; }

# --- Pre-flight Checks & Auto-configuration ---

# A reusable function to prompt for a value and update the .tfvars file
prompt_and_update_tfvar() {
    local prompt_text=$1
    local default_value=$2
    local tfvar_name=$3
    local var_to_set_ref=$4

    read -p "   $prompt_text [default value: $default_value]: " user_input < /dev/tty
    local final_value=${user_input:-$default_value}

	sed -i.bak "s|^[#[:space:]]*${tfvar_name}[[:space:]]*=.*|${tfvar_name} = \"${final_value}\"|g" "$TFVARS_FILE_PATH"

    # Set the variable in the script's global scope
    eval "$var_to_set_ref='$final_value'"
}

# --- State Management ---
write_state() {
    if [ -z "$STATE_FILE" ]; then return; fi
    if ! (
        touch "$STATE_FILE"
        TMP_STATE_FILE=$(mktemp)
        grep -v "^$1=" "$STATE_FILE" > "$TMP_STATE_FILE" || true
        echo "$1=$2" >> "$TMP_STATE_FILE"
        mv "$TMP_STATE_FILE" "$STATE_FILE"
    ); then
        warn "Could not write to state file: $STATE_FILE. Resuming will not be possible from this point."
    fi
}
read_state() {
    if [ -f "$STATE_FILE" ]; then
        info "Found previous state file. Resuming..."
        set -a; source "$STATE_FILE"; set +a
    fi
}

# --- Read GitHub Configuration from Existing tfvars ---
read_github_config_from_tfvars() {
    local tfvars_file=$1
    if [ -f "$tfvars_file" ]; then
        GITHUB_REPO_OWNER=$(grep "^github_repo_owner" "$tfvars_file" | cut -d'"' -f2)
        GITHUB_REPO_NAME=$(grep "^github_repo_name" "$tfvars_file" | cut -d'"' -f2)
        GITHUB_BRANCH=$(grep "^github_branch_name" "$tfvars_file" | cut -d'"' -f2)
        
        if [ -n "$GITHUB_REPO_OWNER" ] && [ -n "$GITHUB_REPO_NAME" ] && [ -n "$GITHUB_BRANCH" ]; then
            return 0  # Successfully read values
        fi
    fi
    return 1  # Could not read values
}

# --- Read Project Configuration from Existing tfvars ---
read_project_config_from_tfvars() {
    local tfvars_file=$1
    if [ -f "$tfvars_file" ]; then
        local gcp_proj=$(grep "^gcp_project_id" "$tfvars_file" | cut -d'"' -f2)
        local gcp_reg=$(grep "^gcp_region" "$tfvars_file" | cut -d'"' -f2)
        local github_conn=$(grep "^github_conn_name" "$tfvars_file" | cut -d'"' -f2)
        
        # Only set if they're real values (not placeholders)
        if [ -n "$gcp_proj" ] && [[ ! "$gcp_proj" =~ "YOUR_" ]]; then
            GCP_PROJECT_ID="$gcp_proj"
        fi
        if [ -n "$gcp_reg" ]; then
            GCP_REGION="$gcp_reg"
        fi
        if [ -n "$github_conn" ]; then
            GITHUB_CONN_NAME="$github_conn"
        fi
    fi
}

# --- Resolve the actual tfvars file in an environment directory ---
resolve_tfvars_path() {
    local env_dir="$1"  # absolute path to environment directory
    local env_name="$2"
    # Prefer <env_name>.tfvars, fall back to any *.tfvars file in the directory
    if [ -f "$env_dir/$env_name.tfvars" ]; then
        echo "$env_dir/$env_name.tfvars"
    else
        local found
        found=$(find "$env_dir" -maxdepth 1 -name "*.tfvars" ! -name "*.bak" | head -n 1)
        echo "$found"
    fi
}

# --- Database Connectivity Helpers ---
start_sql_proxy() {
    info "Starting Cloud SQL Auth Proxy..."
    
    # 1. Get Instance Connection Name
    # Try Terraform output first, fallback to gcloud
    pushd "$REPO_ROOT/infra/environments/$ENV_NAME" > /dev/null
    DB_INSTANCE_NAME=$(terraform output -raw cloud_sql_connection_name 2>/dev/null)
    popd > /dev/null

    if [ -z "$DB_INSTANCE_NAME" ]; then
        DB_INSTANCE_NAME=$(gcloud sql instances list --format="value(connectionName)" --filter="name:creative-studio-db*" --project="$GCP_PROJECT_ID" | head -n 1)
    fi

    if [ -z "$DB_INSTANCE_NAME" ]; then
        fail "Could not find Cloud SQL instance. Ensure Terraform ran successfully."
    fi

    export INSTANCE_CONNECTION_NAME="$DB_INSTANCE_NAME"

    # 2. Download Proxy (if missing)
    if [ ! -f "cloud-sql-proxy" ]; then
        curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.0/cloud-sql-proxy.linux.amd64
        chmod +x cloud-sql-proxy
    fi

    # 3. Start Proxy in Background (Port 5432)
    ./cloud-sql-proxy --address 0.0.0.0 --port 5432 "$DB_INSTANCE_NAME" > /dev/null 2>&1 &
    PROXY_PID=$!
    export PROXY_PID
    
    # 4. Wait for Readiness
    echo -n "   Waiting for proxy connection..."
    for i in {1..30}; do
        if (echo > /dev/tcp/127.0.0.1/5432) >/dev/null 2>&1; then
            echo " Connected!"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo
    warn "Proxy connection check timed out, but proceeding..."
}

stop_sql_proxy() {
    if [ -n "$PROXY_PID" ]; then
        info "Stopping Cloud SQL Proxy..."
        kill "$PROXY_PID" 2>/dev/null || true
        unset PROXY_PID
    fi
}

export_db_vars() {
    # Fetch password from Secret Manager
    DB_PASS=$(gcloud secrets versions access latest --secret="creative-studio-db-password" --project="$GCP_PROJECT_ID")
    
    export DB_USER="studio_user"
    export DB_PASS="$DB_PASS"
    export DB_NAME="creative_studio"
    export DB_HOST="127.0.0.1" # Proxy address
    export DB_PORT="5432"
    export USE_CLOUD_SQL_AUTH_PROXY=true
}

# --- Script Functions ---
check_prerequisites() {
    step 1 "Checking Prerequisites"
    command -v gcloud >/dev/null || fail "gcloud CLI not found. Please install from https://cloud.google.com/sdk/docs/install"
    command -v git >/dev/null || fail "git not found. Please install it."
    if ! command -v jq &> /dev/null; then
        warn "The 'jq' command is required but not found."
        prompt "Would you like to try and install it now? (y/n)"; read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            warn "This may require sudo privileges."
			if command -v apt-get &>/dev/null; then sudo apt-get update && sudo apt-get install -y jq
			elif command -v brew &>/dev/null; then brew install jq
			elif command -v yum &>/dev/null; then sudo yum install -y jq
			else fail "Cannot automatically install jq on this OS. Please install it manually and run again."
			fi
        else fail "Please install jq and run this script again.";
		fi
    fi
    check_and_install_uv
    success "Prerequisites met. gcloud, git, jq, and uv"
}

check_and_install_uv() {
    if command -v uv >/dev/null; then
        info "uv is already installed."
        return
    fi
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
}

get_platform_arch() {
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    case $ARCH in
        x86_64) ARCH="amd64" ;; aarch64) ARCH="arm64" ;; arm64) ARCH="arm64" ;;
    esac
    echo "${OS}_${ARCH}"
}

check_and_install_terraform() {
    step 2 "Checking Terraform Installation"
    if ! command -v terraform &> /dev/null; then
        warn "Terraform is not installed."
        install_terraform
        return
    fi
    INSTALLED_VERSION=$(terraform version -json | jq -r .terraform_version)
    if [[ "$(printf '%s\n' "$REQUIRED_TERRAFORM_VERSION" "$INSTALLED_VERSION" | sort -V | head -n1)" != "$REQUIRED_TERRAFORM_VERSION" ]]; then
        warn "Your Terraform version ($INSTALLED_VERSION) is older than the required version ($REQUIRED_TERRAFORM_VERSION)."
        install_terraform
    else
        success "Terraform version $INSTALLED_VERSION is sufficient."
    fi
}

install_terraform() {
    warn "Terraform is missing or outdated. The required version ($REQUIRED_TERRAFORM_VERSION) will be installed now."
    PLATFORM_ARCH=$(get_platform_arch)
    TF_ZIP_FILENAME="terraform_${REQUIRED_TERRAFORM_VERSION}_${PLATFORM_ARCH}.zip"
    TF_DOWNLOAD_URL="https://releases.hashicorp.com/terraform/${REQUIRED_TERRAFORM_VERSION}/${TF_ZIP_FILENAME}"
    info "Downloading Terraform for your platform (${PLATFORM_ARCH})..."
    curl -Lo terraform.zip "$TF_DOWNLOAD_URL"
    unzip -o terraform.zip
    info "Installing Terraform into the persistent ~/bin directory..."
    mkdir -p "$HOME/bin"
    mv terraform "$HOME/bin/"
    if ! grep -q 'export PATH="$HOME/bin:$PATH"' ~/.bashrc; then
        info "Adding ~/bin to your PATH in ~/.bashrc for future sessions..."
        echo -e '\n# Add local bin to PATH\nexport PATH="$HOME/bin:$PATH"' >> ~/.bashrc
    fi
    export PATH="$HOME/bin:$PATH"
    hash -r
    rm terraform.zip LICENSE.txt
    if command -v terraform &> /dev/null && [[ "$(terraform version -json | jq -r .terraform_version)" == "$REQUIRED_TERRAFORM_VERSION" ]]; then
        success "Terraform v$(terraform -version | head -n 1) is now active."
    else
        fail "Terraform installation failed. Please open a new terminal and run this script again."
    fi
}

setup_project() {
    step 3 "Configuring Google Cloud Project"

    # Try to read from default environment's tfvars if it exists
    if [ -d "infra/environments/$DEFAULT_ENV_NAME" ]; then
        local DEFAULT_TFVARS="infra/environments/$DEFAULT_ENV_NAME/$DEFAULT_ENV_NAME.tfvars"
        if [ -f "$DEFAULT_TFVARS" ]; then
            read_project_config_from_tfvars "$DEFAULT_TFVARS"
            if [ -n "$GCP_PROJECT_ID" ]; then
                info "Detected GCP project ID from existing environment: $GCP_PROJECT_ID"
                prompt "Use this project? (y/n)"
                read -r REPLY < /dev/tty
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    gcloud config set project "$GCP_PROJECT_ID"
                    success "Project '$GCP_PROJECT_ID' is configured."
                    return
                fi
            fi
        fi
    fi

    # try detecting current project on the current terminal
    CURRENT_GCLOUD_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")

    if [ -n "$GCP_PROJECT_ID" ]; then
        prompt "Found project '$GCP_PROJECT_ID' from a previous run. Use this project? (y/n)"; read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            gcloud config set project "$GCP_PROJECT_ID"
            success "Project '$GCP_PROJECT_ID' is configured."
            return
        fi
    elif [ -n "$CURRENT_GCLOUD_PROJECT" ]; then
        prompt "Detected active gcloud project '$CURRENT_GCLOUD_PROJECT'. Use this project? (y/n)"
        read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            GCP_PROJECT_ID=$CURRENT_GCLOUD_PROJECT
            info "Using existing project '$GCP_PROJECT_ID'."
            gcloud config set project "$GCP_PROJECT_ID"
            success "Project '$GCP_PROJECT_ID' is configured."
            return
        fi
    fi
    prompt "Do you already have a Google Cloud Project to use? (y/n)"; read -r REPLY < /dev/tty
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        prompt "Please enter your existing Google Cloud Project ID:"; read -p "   Project ID: " GCP_PROJECT_ID < /dev/tty
    else
        prompt "What is the desired new Google Cloud Project ID? (e.g., my-creative-studio)"; read -p "   Project ID: " GCP_PROJECT_ID < /dev/tty
        prompt "What is your Google Cloud Billing Account ID? (Find it with 'gcloud beta billing accounts list')"; read -p "   Billing Account ID: " BILLING_ACCOUNT_ID < /dev/tty
        info "Creating project '$GCP_PROJECT_ID'..."; gcloud projects create "$GCP_PROJECT_ID" || warn "Project '$GCP_PROJECT_ID' may already exist. Continuing..."
        info "Linking billing account '$BILLING_ACCOUNT_ID'..."; gcloud beta billing projects link "$GCP_PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"
    fi
    info "Setting gcloud config to use project '$GCP_PROJECT_ID'..."; gcloud config set project "$GCP_PROJECT_ID"
    success "Project '$GCP_PROJECT_ID' is configured."
}

setup_repo() {
    step 4 "Configuring Git Repository"

    # Check if we're already in a valid repo with the right structure
    if [[ -d "infra" && -f "bootstrap.sh" ]]; then
        info "Detected existing Creative Studio repository in current directory."
        REPO_ROOT=$(pwd)
        export REPO_ROOT
        
        # Try to detect GitHub info from git remote
        GITHUB_REPO_URL=$(git remote get-url origin 2>/dev/null || echo "")
        if [ -n "$GITHUB_REPO_URL" ]; then
            GITHUB_REPO_OWNER=$(echo "$GITHUB_REPO_URL" | sed -n 's/.*github.com[\/:]\(.*\)\/.*/\1/p')
            GITHUB_REPO_NAME=$(basename "$GITHUB_REPO_URL" .git)
            info "Detected GitHub owner: $GITHUB_REPO_OWNER"
            info "Detected GitHub repo name: $GITHUB_REPO_NAME"
            
            # Try to get branch from git
            SELECTED_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
            DEFAULT_BRANCH_NAME="$SELECTED_BRANCH"
            success "Repository already configured locally."
            return
        fi
    fi

    # Otherwise, prompt for fork and clone
    warn "Please fork the main repository first: ${UPSTREAM_REPO_URL}/fork"
    while true; do
        prompt "What is the git URL of YOUR forked repository? (e.g., https://github.com/user/repo.git)"
        read -p "   Git URL: " GITHUB_REPO_URL < /dev/tty
        if [ -z "$GITHUB_REPO_URL" ]; then warn "Repository URL cannot be empty."; continue; fi
        info "Validating repository URL..."
        if git ls-remote --exit-code -h "$GITHUB_REPO_URL" > /dev/null 2>&1; then
            success "Repository found."; break
        else warn "Repository not found at that URL. Please check for typos and try again."; fi
    done

    # --- Ask for Branch ---
    prompt "Which git branch would you like to use? (default: main)"
    read -p "   Branch Name: " SELECTED_BRANCH < /dev/tty
    SELECTED_BRANCH=${SELECTED_BRANCH:-main}
    DEFAULT_BRANCH_NAME="$SELECTED_BRANCH"

    local REPO_CLONE_DIR=$(basename "$GITHUB_REPO_URL" .git)

    if [[ -d "$REPO_CLONE_DIR" ]]; then
        warn "Directory '$REPO_CLONE_DIR' already exists."; prompt "Do you want to use this existing directory? (y/n)"; read -r REPLY < /dev/tty
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then fail "Please remove the directory or run the script from a different location."; fi
    else
        info "Performing a sparse checkout of '$REPO_CLONE_DIR' (Branch: $SELECTED_BRANCH)..."
        
        # 1. Clone with -b branch_name
        git clone --filter=blob:none --no-checkout --depth 1 --sparse -b "$SELECTED_BRANCH" "$GITHUB_REPO_URL" "$REPO_CLONE_DIR"
        
        cd "$REPO_CLONE_DIR"
        
        # 2. Sparse checkout for ROOT folders only
        git sparse-checkout set "infra" "backend" "frontend" "bootstrap.sh"
        
        git checkout
        cd ..

        success "Repository cloned successfully."
    fi

    # --- Project Path Verification ---
    info "Verifying project structure..."

    # Check if the project is at the top level
    if [[ -d "$REPO_CLONE_DIR/infra" && -f "$REPO_CLONE_DIR/bootstrap.sh" ]]; then
        info "Detected project structure."
    else
        warn "Directory listing of clone:"
        ls -F "$REPO_CLONE_DIR/"
        fail "Could not find a valid project structure. The script requires an 'infra' directory and 'bootstrap.sh' file at the root."
    fi

    cd "$REPO_CLONE_DIR"

    REPO_ROOT=$(pwd)
    export REPO_ROOT
    success "Project root successfully set to: $REPO_ROOT"

    GITHUB_REPO_OWNER=$(git remote get-url origin | sed -n 's/.*github.com\/\(.*\)\/.*/\1/p')
    GITHUB_REPO_NAME=$REPO_CLONE_DIR

    info "Detected GitHub owner: $GITHUB_REPO_OWNER"
    info "Detected GitHub repo name: $GITHUB_REPO_NAME"
}

configure_environment() {
    step 5 "Configuring Terraform Environment";
    cd "$REPO_ROOT/infra"
    if [ -z "$ENV_NAME" ]; then
        prompt "What would you like to call this deployment environment?"; read -p "   Environment Name [default value: $DEFAULT_ENV_NAME]: " ENV_NAME < /dev/tty
        ENV_NAME=${ENV_NAME:-$DEFAULT_ENV_NAME}
    else info "Using previously configured environment: $ENV_NAME"; fi
    ENV_DIR="environments/$ENV_NAME";
    TFVARS_FILE_PATH=$(resolve_tfvars_path "$REPO_ROOT/infra/$ENV_DIR" "$ENV_NAME")
    STATE_FILE="$REPO_ROOT/infra/$ENV_DIR/.bootstrap_state";
    read_state
    
    # Check if environment already exists and read existing config
    if [ -d "$ENV_DIR" ] && [ -f "$TFVARS_FILE_PATH" ]; then
        info "Environment directory '$ENV_DIR' already exists."
        if read_github_config_from_tfvars "$TFVARS_FILE_PATH"; then
            info "Loaded GitHub configuration from existing tfvars:"
            info "  Owner: $GITHUB_REPO_OWNER"
            info "  Repo: $GITHUB_REPO_NAME"
            info "  Branch: $GITHUB_BRANCH"
            success "Configuration files for '$ENV_NAME' environment are ready."
            return
        fi
    fi
    
    if [ ! -d "$ENV_DIR" ]; then
        info "Creating new environment directory from template: $TEMPLATE_ENV_DIR"; cp -r "$TEMPLATE_ENV_DIR" "$ENV_DIR"
        prompt "Do you have an existing GCS bucket for Terraform state? (y/n)"; read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            prompt "Please enter the name of your GCS bucket:"; read -p "   Bucket Name: " BUCKET_NAME < /dev/tty
        else
            BUCKET_SUFFIX=$(printf "$GCS_BUCKET_SUFFIX_FORMAT" "$ENV_NAME"); BUCKET_NAME="${GCP_PROJECT_ID}-${BUCKET_SUFFIX}"
            info "Creating GCS bucket '$BUCKET_NAME' for Terraform state..."; gsutil mb -p "$GCP_PROJECT_ID" "gs://${BUCKET_NAME}" || warn "Bucket 'gs://${BUCKET_NAME}' may already exist. Continuing..."
        fi
        BUCKET_PREFIX=$(printf "$GCS_BUCKET_PREFIX_FORMAT" "$ENV_NAME")
        info "Updating backend.tf with default prefix: $BUCKET_PREFIX"; echo "terraform {
  backend \"gcs\" {
    bucket = \"$BUCKET_NAME\"
    prefix = \"$BUCKET_PREFIX\"
  }
}" > "$ENV_DIR/backend.tf"
        info "Updating $TFVARS_FILE_PATH...";
        mv "$ENV_DIR/dev.tfvars" "$TFVARS_FILE_PATH"

        sed -i.bak "s|^[#[:space:]]*gcp_project_id[[:space:]]*=.*|gcp_project_id = \"$GCP_PROJECT_ID\"|g" "$TFVARS_FILE_PATH"
        sed -i.bak "s|^[#[:space:]]*github_repo_owner[[:space:]]*=.*|github_repo_owner = \"$GITHUB_REPO_OWNER\"|g" "$TFVARS_FILE_PATH"
        sed -i.bak "s|^[#[:space:]]*github_repo_name[[:space:]]*=.*|github_repo_name = \"$GITHUB_REPO_NAME\"|g" "$TFVARS_FILE_PATH"

        # Set service names automatically
        info "Default service names will be '$BE_SERVICE_NAME' and '$FE_SERVICE_NAME'."
        sed -i.bak "s|^[#[:space:]]*backend_service_name[[:space:]]*=.*|backend_service_name = \"$BE_SERVICE_NAME\"|g" "$TFVARS_FILE_PATH"
        sed -i.bak "s|^[#[:space:]]*frontend_service_name[[:space:]]*=.*|frontend_service_name = \"$FE_SERVICE_NAME\"|g" "$TFVARS_FILE_PATH"

        # Prompt only for the branch name
        export TFVARS_FILE=$TFVARS_FILE_PATH # Set context for helper function
        prompt "Please provide the following value:"
        prompt_and_update_tfvar "GitHub Branch to deploy from" "$DEFAULT_BRANCH_NAME" "github_branch_name" "GITHUB_BRANCH"

        write_state "ENV_NAME" "$ENV_NAME"; write_state "BE_SERVICE_NAME" "$BE_SERVICE_NAME"; write_state "FE_SERVICE_NAME" "$FE_SERVICE_NAME"; write_state "GITHUB_BRANCH" "$GITHUB_BRANCH"
    else info "Environment directory '$ENV_DIR' already configured."; fi
    success "Configuration files for '$ENV_NAME' environment are ready."
}

handle_manual_steps() {
    step 6 "Manual Steps Required"; cd "$REPO_ROOT/infra"
    TFVARS_FILE_PATH=$(resolve_tfvars_path "$REPO_ROOT/infra/$ENV_DIR" "$ENV_NAME")
    
    # Try to read project config from existing tfvars to avoid re-prompting
    if [ -f "$TFVARS_FILE_PATH" ]; then
        read_project_config_from_tfvars "$TFVARS_FILE_PATH"
    fi
    
    info "Enabling required Google Cloud APIs..."; gcloud services enable cloudbuild.googleapis.com secretmanager.googleapis.com iap.googleapis.com identitytoolkit.googleapis.com texttospeech.googleapis.com workflows.googleapis.com --project="$GCP_PROJECT_ID"
    
    if [ -z "$GITHUB_CONN_NAME" ]; then
        prompt "\nDo you already have a Cloud Build Host Connection for GitHub in this project? (y/n)"; read -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then prompt "Please enter the existing connection name:"; read -p "   Connection Name: " GITHUB_CONN_NAME < /dev/tty
        else
            warn "You will now be guided to create a new GitHub connection."; info "Please perform the following manual steps:"
            echo "1. Open this URL in your browser:"; echo -e "   ${C_YELLOW}https://console.cloud.google.com/cloud-build/connections/create?project=${GCP_PROJECT_ID}${C_RESET}"
            echo "2. Select 'GitHub (Cloud Build GitHub App)' and click 'CONTINUE'."
            echo "3. Follow the prompts to authorize the app on your GitHub account."; 
            echo "4. Grant access to your forked repository: '${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}'."
            echo "5. After creating the connection, copy its name (e.g., 'gh-yourname-con')."
            prompt "Paste the new Cloud Build Connection Name here:"; read -p "   Connection Name: " GITHUB_CONN_NAME < /dev/tty
        fi
        sed -i.bak "s|^[#[:space:]]*github_conn_name[[:space:]]*=.*|github_conn_name = \"$GITHUB_CONN_NAME\"|g" "$TFVARS_FILE_PATH"
        write_state "GITHUB_CONN_NAME" "$GITHUB_CONN_NAME"
    else
        info "Using existing Cloud Build connection: $GITHUB_CONN_NAME"
    fi
    rm -f "$TFVARS_FILE_PATH.bak"

    # --- Automate .tfvars placeholder replacement ---
    info "\nConfiguring IAP OAuth Client ID and Project ID in .tfvars file..."
    if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then
        warn "The IAP OAuth Client ID is required for the .tfvars file."
        echo "1. Open this URL in your browser to find your OAuth Client ID:"
        echo -e "   ${C_YELLOW}https://console.cloud.google.com/apis/credentials?project=${GCP_PROJECT_ID}${C_RESET}"
        echo "2. Find the OAuth 2.0 Client ID of type 'Web application' used by IAP."
        prompt "Paste the IAP OAuth Client ID here:"
        read -p "   Client ID: " AUTO_OAUTH_CLIENT_ID < /dev/tty
        if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then fail "IAP OAuth Client ID is required to proceed."; fi
    fi

    sed -i.bak "s|YOUR_IAP_OAUTH_CLIENT_ID_HERE|$AUTO_OAUTH_CLIENT_ID|g" "$TFVARS_FILE_PATH"
    sed -i.bak "s|YOUR_GCP_PROJECT_ID|$GCP_PROJECT_ID|g" "$TFVARS_FILE_PATH"
    success "Replaced placeholders in $TFVARS_FILE_PATH."
}

populate_oauth_secrets() {
    step 9 "Automating IAP / OAuth Secret Population"
    cd "$REPO_ROOT"

    if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then
        info "Looking for an IAP OAuth 2.0 Web Client ID..."
        AUTO_OAUTH_CLIENT_ID=$(gcloud iap oauth-clients list "$GCP_PROJECT_ID" --format="json" 2>/dev/null | jq -r '.[0].clientId // .[0].name // empty' | awk -F'/' '{print $NF}')
    fi

    if [ -z "$AUTO_OAUTH_CLIENT_ID" ] || [ "$AUTO_OAUTH_CLIENT_ID" == "null" ]; then
        warn "Could not automatically find the IAP OAuth Client ID."
        info "Please perform the following manual steps:"
        echo "1. Open this URL in your browser to find your OAuth Client ID:"
        echo -e "   ${C_YELLOW}https://console.cloud.google.com/apis/credentials?project=${GCP_PROJECT_ID}${C_RESET}"
        echo "2. Find the OAuth 2.0 Client ID of type 'Web application' used by IAP."
        prompt "Paste the IAP OAuth Client ID here:"
        read -p "   Client ID: " AUTO_OAUTH_CLIENT_ID < /dev/tty
        if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then
            fail "IAP OAuth Client ID is required to proceed. Please restart the script."
        fi
    else
        info "Using IAP OAuth Client ID: ${C_YELLOW}${AUTO_OAUTH_CLIENT_ID}${C_RESET}"
    fi

    info "Populating secrets with Client ID: ${C_YELLOW}${AUTO_OAUTH_CLIENT_ID}${C_RESET}"
    # IAP_CLIENT_ID: SPA logout URL only.
    # IAP_AUDIENCE for Cloud Run IAP is the service resource name, NOT the OAuth client ID:
    #   /projects/PROJECT_NUMBER/locations/REGION/services/FRONTEND_SERVICE
    # That value is set as a Cloud Run env var by Terraform (platform module).
    echo -n "$AUTO_OAUTH_CLIENT_ID" | gcloud secrets versions add IAP_CLIENT_ID --data-file="-" --project="$GCP_PROJECT_ID" --quiet
    # Keep GOOGLE_TOKEN_AUDIENCE as client ID for any legacy GIS checks; IAP verify uses IAP_AUDIENCE env.
    echo -n "$AUTO_OAUTH_CLIENT_ID" | gcloud secrets versions add GOOGLE_TOKEN_AUDIENCE --data-file="-" --project="$GCP_PROJECT_ID" --quiet

    local PROJECT_NUMBER FE_SERVICE_NAME IAP_AUD REGION
    PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')
    REGION=$(grep 'gcp_region' "$TFVARS_FILE_PATH" | awk -F'"' '{print $2}')
    REGION=${REGION:-europe-west3}
    FE_SERVICE_NAME=$(grep -E '^\s*frontend_service_name\s*=' "$TFVARS_FILE_PATH" | head -1 | sed -E 's/.*=\s*"([^"]+)".*/\1/' || true)
    FE_SERVICE_NAME=${FE_SERVICE_NAME:-cstudio-frontend-dev}
    IAP_AUD="/projects/${PROJECT_NUMBER}/locations/${REGION}/services/${FE_SERVICE_NAME}"
    echo -n "$IAP_AUD" | gcloud secrets versions add IAP_AUDIENCE --data-file="-" --project="$GCP_PROJECT_ID" --quiet || true
    success "Secrets populated. IAP JWT audience (Cloud Run): ${C_YELLOW}${IAP_AUD}${C_RESET}"

    info "Updating audiences in $TFVARS_FILE_PATH..."
    sed -i.bak "s|YOUR_IAP_OAUTH_CLIENT_ID_HERE|$AUTO_OAUTH_CLIENT_ID|g" "$TFVARS_FILE_PATH"
    rm -f "$TFVARS_FILE_PATH.bak"
    success "Audiences updated in .tfvars file."
}

setup_db_secrets() {
    step 7 "Configuring Database Secrets"
    
    # 1. Enable required APIs first
    info "Enabling Secret Manager and SQL Admin APIs..."
    gcloud services enable secretmanager.googleapis.com sqladmin.googleapis.com --project="$GCP_PROJECT_ID"

    local SECRET_NAME="creative-studio-db-password"
    
    # 2. Check if the secret already exists
    if gcloud secrets describe "$SECRET_NAME" --project="$GCP_PROJECT_ID" > /dev/null 2>&1; then
        info "Secret '$SECRET_NAME' already exists. Skipping creation."
    else
        info "Creating new secret '$SECRET_NAME'..."
        
        # 3. Generate a secure random password that satisfies COMPLEXITY_DEFAULT policy:
        # must contain lowercase, uppercase, number, and non-alphanumeric character.
        # Avoid chars that break shell or DB connection strings (@, :, /, #, ?)
        local DB_PASSWORD
        while true; do
            DB_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9!$%^&*_+=' | head -c 24)
            # Verify all complexity requirements are met
            if echo "$DB_PASSWORD" | grep -q '[a-z]' && \
               echo "$DB_PASSWORD" | grep -q '[A-Z]' && \
               echo "$DB_PASSWORD" | grep -q '[0-9]' && \
               echo "$DB_PASSWORD" | grep -q '[!$%^&*_+=]'; then
                break
            fi
        done
        
        # 4. Create the secret and add the first version
        # We use printf to avoid trailing newlines
        # Use user-managed replication in the project region to comply with
        # org policy constraints/gcp.resourceLocations (global replication is blocked)
        local SECRET_REGION
        SECRET_REGION=$(grep "^gcp_region" "$TFVARS_FILE_PATH" 2>/dev/null | cut -d'"' -f2)
        SECRET_REGION=${SECRET_REGION:-europe-west3}
        printf "%s" "$DB_PASSWORD" | gcloud secrets create "$SECRET_NAME" \
            --data-file=- \
            --replication-policy="user-managed" \
            --locations="$SECRET_REGION" \
            --project="$GCP_PROJECT_ID" \
            --quiet

        success "Secret '$SECRET_NAME' created successfully."
    fi
}

# Seed initial versions for the IAP/token secrets that the Cloud Run services
# mount at "versions/latest". Terraform only creates empty secret shells, so the
# services fail to start unless a version exists first. Only seeds a secret that
# exists but has no accessible version, so it is safe to run repeatedly.
seed_required_secret_versions() {
    local client_id="$1"
    if [ -z "$client_id" ]; then
        warn "No OAuth client ID available to seed secrets. Cloud Run may fail until 'populate_oauth_secrets' runs."
        return
    fi
    local s
    for s in GOOGLE_TOKEN_AUDIENCE IAP_CLIENT_ID; do
        if gcloud secrets describe "$s" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
            if gcloud secrets versions access latest --secret="$s" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
                info "Secret '$s' already has a version. Skipping seed."
            else
                info "Seeding initial version for secret '$s'..."
                echo -n "$client_id" | gcloud secrets versions add "$s" --data-file="-" --project="$GCP_PROJECT_ID" --quiet
            fi
        fi
    done
}

run_terraform() {
    step 8 "Deploying Infrastructure with Terraform";
    info "Navigating to $REPO_ROOT/infra/environments/$ENV_NAME..."; cd "$REPO_ROOT/infra/environments/$ENV_NAME"
    TFVARS_FILE_PATH=$(resolve_tfvars_path "$REPO_ROOT/infra/environments/$ENV_NAME" "$ENV_NAME")
    info "Initializing Terraform..."; terraform init -reconfigure
    info "Planning Terraform changes..."; terraform plan -var-file="$TFVARS_FILE_PATH"
    prompt "\nTerraform is ready to apply the changes. This will create the infrastructure, including empty secret shells."; prompt "Do you want to proceed with 'terraform apply'? (y/n)"; read -r REPLY < /dev/tty
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then warn "Apply cancelled."; return; fi

    # --- Phase 1/2: create the Secret Manager shells first, so their versions
    # can be seeded BEFORE the Cloud Run services (which mount them) are created.
    # Prevents "Secret .../versions/latest was not found" on the first apply. ---
    info "Phase 1/2: Creating Secret Manager shells..."
    terraform apply -auto-approve -var-file="$TFVARS_FILE_PATH" \
        -target=module.creative_studio_platform.module.backend_secrets \
        -target=module.creative_studio_platform.module.frontend_secrets

    # Resolve an OAuth client ID to seed the IAP/token secrets with.
    local SEED_CLIENT_ID="$AUTO_OAUTH_CLIENT_ID"
    if [ -z "$SEED_CLIENT_ID" ]; then
        SEED_CLIENT_ID=$(grep -E '^[[:space:]]*backend_custom_audiences' "$TFVARS_FILE_PATH" 2>/dev/null | grep -oE '[0-9]+-[A-Za-z0-9_]+\.apps\.googleusercontent\.com' | head -1)
    fi
    seed_required_secret_versions "$SEED_CLIENT_ID"

    # --- Phase 2/2: apply the full infrastructure now that the secrets have versions. ---
    info "Phase 2/2: Applying full infrastructure..."
    terraform apply -auto-approve -var-file="$TFVARS_FILE_PATH" -parallelism=30
}

update_oauth_client() {
    step 10 "Configuring OAuth Client URIs"; cd "$REPO_ROOT"
    TFVARS_FILE_PATH="${TFVARS_FILE_PATH:-$(resolve_tfvars_path "$REPO_ROOT/infra/environments/$ENV_NAME" "$ENV_NAME")}"
    if [ -z "$AUTO_OAUTH_CLIENT_ID" ]; then warn "Could not find IAP OAuth Client ID. Skipping URI update."; return; fi
    info "Fetching full OAuth client name..."; local OAUTH_CLIENT_FULL_NAME=$(gcloud iap oauth-clients list "$GCP_PROJECT_ID" --format="json" | jq -r --arg clientid "$AUTO_OAUTH_CLIENT_ID" '.[] | select(.name | contains($clientid) or .clientId == $clientid) | .name' | head -n 1)
    if [ -z "$OAUTH_CLIENT_FULL_NAME" ]; then warn "Could not resolve the full name for the OAuth client. Skipping URI update."; return; fi

    local PROJECT_NUMBER REGION FE_URL IAP_REDIRECT_URI
    PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')
    REGION=$(grep 'gcp_region' "$TFVARS_FILE_PATH" | awk -F'"' '{print $2}')
    REGION=${REGION:-us-central1}
    FE_URL="https://${FE_SERVICE_NAME}-${PROJECT_NUMBER}.${REGION}.run.app"
    IAP_REDIRECT_URI="https://iap.googleapis.com/v1/oauth/clientIds/${AUTO_OAUTH_CLIENT_ID}:handleRedirect"

    info "Ensuring OAuth Client has Cloud Run frontend origins and IAP redirect URIs..."
    info "  JS origin: ${C_YELLOW}${FE_URL}${C_RESET}"
    gcloud iap oauth-clients update "$OAUTH_CLIENT_FULL_NAME" \
        --add-javascript-origins="$FE_URL" \
        --add-redirect-uris="$IAP_REDIRECT_URI" \
        --add-redirect-uris="${FE_URL}/" \
        --project="$GCP_PROJECT_ID" --quiet
    success "OAuth Client URIs configured for Cloud Run frontend."
}

update_secrets() {
    step 11 "Updating Remaining Secrets"; info "Navigating to $REPO_ROOT/infra/environments/$ENV_NAME..."; cd "$REPO_ROOT/infra/environments/$ENV_NAME"
    info "Populating values in Secret Manager..."; local TERRAFORM_OUTPUTS=$(terraform output -json)
    local FRONTEND_SECRETS=$(echo "$TERRAFORM_OUTPUTS" | jq -r .frontend_secrets.value[]); local BACKEND_SECRETS=$(echo "$TERRAFORM_OUTPUTS" | jq -r .backend_secrets.value[])
    local ALL_SECRETS=$(echo "${FRONTEND_SECRETS} ${BACKEND_SECRETS}" | tr ' ' '\n' | sort -u | grep .)
    if [ -z "$ALL_SECRETS" ]; then success "No secrets defined in Terraform outputs. Nothing to do."; return; fi

    for SECRET_NAME in $ALL_SECRETS; do
        info "Processing secret: ${C_YELLOW}${SECRET_NAME}${C_RESET}"

        SECRET_VALUE=""
        AUTO_DISCOVERED=false

        # IAP / OAuth secrets are handled by populate_oauth_secrets
        case $SECRET_NAME in
            "IAP_CLIENT_ID"|"IAP_AUDIENCE"|"GOOGLE_TOKEN_AUDIENCE"|"GOOGLE_CLIENT_ID")
                info "  Value is handled by the IAP/OAuth population step. Skipping."; continue ;;
        esac

        if [ "$AUTO_DISCOVERED" = true ] && [ -n "$SECRET_VALUE" ]; then
            info "  Value was auto-detected. Populating automatically."
            echo -n "$SECRET_VALUE" | gcloud secrets versions add "$SECRET_NAME" --data-file="-" --project="$GCP_PROJECT_ID" --quiet
            success "  Successfully added new version for ${SECRET_NAME}."

        else
            # This fallback is for secrets that are not auto-discovered
            warn "  This secret requires manual input."
            echo -e "${C_CYAN}  It is safe to paste your secret. The value is read securely, not displayed, and not stored in history.${C_RESET}"
            read -s -p "  Enter new value: " SECRET_VALUE < /dev/tty; echo

            if [ -z "$SECRET_VALUE" ]; then warn "  No value provided. Skipping ${SECRET_NAME}."; continue; fi
            echo -n "$SECRET_VALUE" | gcloud secrets versions add "$SECRET_NAME" --data-file="-" --project="$GCP_PROJECT_ID" --quiet
            success "  Successfully added new version for ${SECRET_NAME}."
        fi
    done; success "All secrets have been populated."
}

seed_data() {
    step 12 "Seeding Initial Data (Workspaces, Templates, Assets)"
    cd "$REPO_ROOT"

    info "The user running this script will be set as the owner of initial data."
    local CURRENT_USER=$(gcloud config get-value account 2>/dev/null)
    if [ -z "$CURRENT_USER" ]; then
      warn "Could not determine current gcloud user. Defaulting to 'system' owner in bootstrap script."
      CURRENT_USER="system"
    fi

    info "Project:      ${C_YELLOW}${GCP_PROJECT_ID}${C_RESET}"
    info "Deploying as: ${C_YELLOW}${CURRENT_USER}${C_RESET}"

    # Establish Database Connectivity
    export_db_vars
    start_sql_proxy
    # Ensure proxy stops even if this function fails
    trap stop_sql_proxy EXIT

    # Temporarily change to the project root so Python module resolution works
    pushd "$REPO_ROOT" > /dev/null

    # 1. Manually construct the CORRECT asset bucket name
    local ASSET_BUCKET_NAME="${GCP_PROJECT_ID}-cs-development-bucket"
    success "Using asset bucket: gs://${ASSET_BUCKET_NAME}"

    info "Setting bootstrap script environment variables..."
    export GOOGLE_CLOUD_PROJECT=$GCP_PROJECT_ID
    export ADMIN_USER_EMAIL=$CURRENT_USER
    export GENMEDIA_BUCKET=$ASSET_BUCKET_NAME

    local PYTHON_SCRIPT_PATH="backend/bootstrap/bootstrap.py"
    if [ ! -f "$PYTHON_SCRIPT_PATH" ]; then
        fail "Bootstrap script not found at: ${PYTHON_SCRIPT_PATH}"
    fi

    # --- Set up virtual environment and install dependencies using uv ---
    info "Setting up Python virtual environment for data seeding using uv..."
    VENV_DIR="$REPO_ROOT/backend/.venv"
    PYPROJECT_FILE="$REPO_ROOT/backend/pyproject.toml"

    if [ ! -f "$PYPROJECT_FILE" ]; then
        popd > /dev/null
        fail "Python project file not found at '$PYPROJECT_FILE'."
    fi

    # Create venv if it doesn't exist
    uv venv "$VENV_DIR" --python python3

    # Install dependencies from pyproject.toml into the virtual environment
    info "Installing Python project and its dependencies from 'backend/pyproject.toml'..."
    # Use an editable install (-e) to ensure all project dependencies are installed.
    uv pip install --python "$VENV_DIR/bin/python" -e backend

    info "Executing Python bootstrap script..."
    # We `cd` into the backend directory so that relative paths to assets inside the python script resolve correctly.
    # The editable install ensures that `from src...` imports work without needing PYTHONPATH.
    if (cd backend && "$VENV_DIR/bin/python" -m bootstrap.bootstrap); then
        success "Python bootstrap script executed successfully."
    else
        fail "Python bootstrap script failed."
    fi

    # Return to the original directory
    popd > /dev/null

    # Cleanup
    stop_sql_proxy
    trap - EXIT
}



trigger_builds() {
    step 13 "Triggering Initial Builds"; cd "$REPO_ROOT"
    TFVARS_FILE_PATH="${TFVARS_FILE_PATH:-$(resolve_tfvars_path "$REPO_ROOT/infra/environments/$ENV_NAME" "$ENV_NAME")}"
    prompt "Would you like to trigger the initial builds for the frontend and backend now? (y/n)"; read -r REPLY < /dev/tty
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then info "You can trigger the builds manually later by pushing a commit or via the Cloud Build UI."; return; fi
    local REGION
    REGION=$(grep 'gcp_region' "$TFVARS_FILE_PATH" | awk -F'"' '{print $2}')
    REGION=${REGION:-us-central1}
    info "Triggering backend build..."; gcloud builds triggers run "${BE_SERVICE_NAME}-trigger" --branch="$GITHUB_BRANCH" --project="$GCP_PROJECT_ID" --region="$REGION"
    info "Triggering frontend build..."; gcloud builds triggers run "${FE_SERVICE_NAME}-trigger" --branch="$GITHUB_BRANCH" --project="$GCP_PROJECT_ID" --region="$REGION"

    success "Builds have been triggered."; info "You can monitor their progress in the Cloud Build console:"; echo -e "   ${C_YELLOW}https://console.cloud.google.com/cloud-build/builds?project=${GCP_PROJECT_ID}${C_RESET}"
}

configure_iap() {
    step 14 "Enabling IAP on Frontend Cloud Run"
    cd "$REPO_ROOT"
    TFVARS_FILE_PATH="${TFVARS_FILE_PATH:-$(resolve_tfvars_path "$REPO_ROOT/infra/environments/$ENV_NAME" "$ENV_NAME")}"

    local REGION PROJECT_NUMBER
    REGION=$(grep 'gcp_region' "$TFVARS_FILE_PATH" | awk -F'"' '{print $2}')
    REGION=${REGION:-us-central1}
    PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')

    info "Frontend Cloud Run service: ${C_YELLOW}${FE_SERVICE_NAME}${C_RESET} (region: ${REGION})"
    info "After the frontend deploy completes, IAP will gate access to:"
    echo -e "   ${C_YELLOW}https://${FE_SERVICE_NAME}-${PROJECT_NUMBER}.${REGION}.run.app${C_RESET}"

    prompt "Enable IAP on the frontend Cloud Run service now? (y/n)"; read -r REPLY < /dev/tty
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        warn "Skipping IAP enablement. You can run these commands later:"
        echo "  gcloud run services update ${FE_SERVICE_NAME} --region=${REGION} --iap --project=${GCP_PROJECT_ID}"
        echo "  gcloud beta services identity create --service=iap.googleapis.com --project=${GCP_PROJECT_ID}"
        echo "  gcloud run services add-iam-policy-binding ${FE_SERVICE_NAME} --region=${REGION} --project=${GCP_PROJECT_ID} \\"
        echo "    --member=serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com --role=roles/run.invoker"
        echo "  gcloud iap web add-iam-policy-binding --resource-type=cloud-run --service=${FE_SERVICE_NAME} --region=${REGION} --project=${GCP_PROJECT_ID} \\"
        echo "    --member=user:USER_EMAIL --role=roles/iap.httpsResourceAccessor"
        return
    fi

    info "Enabling IAP on Cloud Run service '${FE_SERVICE_NAME}'..."
    echo -e "   ${C_CYAN}gcloud run services update ${FE_SERVICE_NAME} --region=${REGION} --iap --project=${GCP_PROJECT_ID}${C_RESET}"
    gcloud run services update "$FE_SERVICE_NAME" --region="$REGION" --iap --project="$GCP_PROJECT_ID" --quiet

    info "Ensuring IAP service agent exists..."
    echo -e "   ${C_CYAN}gcloud beta services identity create --service=iap.googleapis.com --project=${GCP_PROJECT_ID}${C_RESET}"
    gcloud beta services identity create --service=iap.googleapis.com --project="$GCP_PROJECT_ID" --quiet || true

    info "Granting Cloud Run Invoker to the IAP service agent..."
    echo -e "   ${C_CYAN}gcloud run services add-iam-policy-binding ${FE_SERVICE_NAME} --region=${REGION} --member=serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com --role=roles/run.invoker${C_RESET}"
    gcloud run services add-iam-policy-binding "$FE_SERVICE_NAME" \
        --region="$REGION" \
        --project="$GCP_PROJECT_ID" \
        --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
        --role="roles/run.invoker" \
        --quiet

    prompt "Grant IAP access (roles/iap.httpsResourceAccessor). Enter a domain (e.g. example.com) or user email (leave blank to skip):"
    read -p "   Member: " IAP_MEMBER < /dev/tty
    if [ -n "$IAP_MEMBER" ]; then
        local MEMBER_SPEC
        if [[ "$IAP_MEMBER" == *@* ]]; then
            MEMBER_SPEC="user:${IAP_MEMBER}"
        else
            MEMBER_SPEC="domain:${IAP_MEMBER}"
        fi
        info "Granting ${MEMBER_SPEC} roles/iap.httpsResourceAccessor on frontend Cloud Run..."
        echo -e "   ${C_CYAN}gcloud iap web add-iam-policy-binding --resource-type=cloud-run --service=${FE_SERVICE_NAME} --region=${REGION} --member=${MEMBER_SPEC} --role=roles/iap.httpsResourceAccessor${C_RESET}"
        gcloud iap web add-iam-policy-binding \
            --resource-type=cloud-run \
            --service="$FE_SERVICE_NAME" \
            --region="$REGION" \
            --project="$GCP_PROJECT_ID" \
            --member="$MEMBER_SPEC" \
            --role="roles/iap.httpsResourceAccessor" \
            --quiet
        success "IAP access granted to ${MEMBER_SPEC}."
    else
        warn "No IAP accessor granted. Users will not be able to reach the frontend until you grant roles/iap.httpsResourceAccessor."
    fi

    success "IAP configured on frontend Cloud Run service '${FE_SERVICE_NAME}'."
}

# --- Main Execution ---
main() {
    echo -e "${C_GREEN}============================================================${C_RESET}"
    echo -e "${C_GREEN} 🚀  Welcome to the Creative Studio Infrastructure Setup 🚀 ${C_RESET}"
    echo -e "${C_GREEN}============================================================${C_RESET}"

    echo -e "${C_BLUE}"
    echo -e " ██████ ██████  ███████  █████  ████████ ██ ██    ██ ███████     ███████ ████████ ██    ██ ██████  ██  ██████  "
    echo -e "██      ██   ██ ██      ██   ██    ██    ██ ██    ██ ██          ██         ██    ██    ██ ██   ██ ██ ██    ██ "
    echo -e "██      ██████  █████   ███████    ██    ██ ██    ██ █████       ███████    ██    ██    ██ ██   ██ ██ ██    ██ "
    echo -e "██      ██   ██ ██      ██   ██    ██    ██  ██  ██  ██               ██    ██    ██    ██ ██   ██ ██ ██    ██ "
    echo -e " ██████ ██   ██ ███████ ██   ██    ██    ██   ████   ███████     ███████    ██     ██████  ██████  ██  ██████   "
    echo -e "${C_RESET}"

    read_state; LAST_COMPLETED_STEP=${LAST_COMPLETED_STEP:-0}
    declare -a steps_to_run=(
        "check_prerequisites"
        "check_and_install_terraform"
        "setup_project" "setup_repo"
        "configure_environment"
        "handle_manual_steps"
        "setup_db_secrets"
        "run_terraform"
        "populate_oauth_secrets"
        "update_oauth_client"
        "update_secrets"
        "seed_data"
        "trigger_builds"
        "configure_iap"
    )
    for i in "${!steps_to_run[@]}"; do
        step_num=$((i + 1))
        if (( LAST_COMPLETED_STEP < step_num )); then
            if [ -z "$STATE_FILE" ] && [ "$step_num" -gt 4 ]; then
                STATE_FILE="$REPO_ROOT/infra/environments/$ENV_NAME/.bootstrap_state"
                write_state "REPO_ROOT" "$REPO_ROOT"
            fi
            ${steps_to_run[$i]}; write_state "LAST_COMPLETED_STEP" "$step_num"
        fi
    done

    step 15 "🎉 Deployment Complete! 🎉";
    info "Fetching your application URLs...";
    cd "$REPO_ROOT/infra/environments/$ENV_NAME"

    # Prefer terraform output; fall back to predictable Cloud Run URL
    FRONTEND_URL=$(terraform output -raw frontend_service_url 2>/dev/null || echo "")
    if [ -z "$FRONTEND_URL" ]; then
        warn "Could not find 'frontend_service_url' in Terraform outputs. Constructing Cloud Run URL."
        local PROJECT_NUMBER REGION
        PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')
        REGION=$(grep 'gcp_region' "$TFVARS_FILE_PATH" | awk -F'"' '{print $2}')
        REGION=${REGION:-us-central1}
        FRONTEND_URL="https://${FE_SERVICE_NAME}-${PROJECT_NUMBER}.${REGION}.run.app"
    fi

    # Get the backend URL
    BACKEND_URL=$(terraform output -raw backend_service_url 2>/dev/null || echo "")
    if [ -z "$BACKEND_URL" ]; then
        warn "Could not find 'backend_service_url' in Terraform outputs."
    fi

    success "Your infrastructure is ready."
    echo "------------------------------------------------------------------"; echo -e "   Frontend URL (Cloud Run + IAP): ${C_YELLOW}${FRONTEND_URL}${C_RESET}"; echo -e "   Backend URL:  ${C_YELLOW}${BACKEND_URL}${C_RESET}"; echo "------------------------------------------------------------------"
    info "It may take a few minutes for the builds to complete and the services to become available."
    info "Access to the frontend is controlled by IAP (roles/iap.httpsResourceAccessor)."

    echo # Add a blank line for spacing
    info "Thanks for using Creative Studio!"
    info "We'd love your feedback: ${C_YELLOW}https://docs.google.com/forms/d/e/1FAIpQLSceWvu7G354h-dTbOGvNGEraEjcUAgPE300WNY5qr-WJbh3Eg/viewform${C_RESET}"
    echo -e "${C_GREEN}============================================================${C_RESET}"
}

main "$@"
