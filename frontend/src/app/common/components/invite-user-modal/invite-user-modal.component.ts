/**
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {WorkspaceRole} from '../../models/workspace-member.model';
import {Workspace} from '../../models/workspace.model';
import {WorkspaceService} from '../../../services/workspace/workspace.service';

export interface InviteUserData {
  workspaceName?: string;
  adminMode?: boolean;
}

@Component({
  selector: 'app-invite-user-modal',
  templateUrl: './invite-user-modal.component.html',
})
export class InviteUserModalComponent implements OnInit {
  inviteForm: FormGroup;
  roles = [WorkspaceRole.USER, WorkspaceRole.ADMIN];
  workspaces: Workspace[] = [];
  isLoading = false;

  constructor(
    public dialogRef: MatDialogRef<InviteUserModalComponent>,
    @Inject(MAT_DIALOG_DATA) public data: InviteUserData,
    private fb: FormBuilder,
    private workspaceService: WorkspaceService,
  ) {
    const formConfig: Record<string, unknown> = {
      email: ['', [Validators.required, Validators.email]],
      role: [WorkspaceRole.USER, Validators.required],
    };

    if (this.data.adminMode) {
      formConfig['workspaceId'] = ['', Validators.required];
    }

    this.inviteForm = this.fb.group(formConfig);
  }

  ngOnInit(): void {
    if (this.data.adminMode) {
      this.isLoading = true;
      this.workspaceService.getAllWorkspacesAdmin().subscribe({
        next: (workspaces: Workspace[]) => {
          this.workspaces = workspaces;
          this.isLoading = false;
        },
        error: err => {
          console.error('Error loading workspaces:', err);
          this.isLoading = false;
        },
      });
    }
  }

  onNoClick(): void {
    this.dialogRef.close();
  }
}
