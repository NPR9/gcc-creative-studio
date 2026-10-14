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

import {NgModule} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule, ReactiveFormsModule} from '@angular/forms';
import {AdminRoutingModule} from './admin-routing.module';
import {AdminLayoutComponent} from './admin-layout/admin-layout.component';
import {UsersManagementComponent} from './users-management/users-management.component';
import {UserFormComponent} from './users-management/user-form.component';
import {MatSidenavModule} from '@angular/material/sidenav';
import {MatListModule} from '@angular/material/list';
import {MatIconModule} from '@angular/material/icon';
import {MatToolbarModule} from '@angular/material/toolbar';
import {MatButtonModule} from '@angular/material/button';
import {MatTableModule} from '@angular/material/table';
import {MatPaginatorModule} from '@angular/material/paginator';
import {MatSortModule} from '@angular/material/sort';
import {MatFormFieldModule} from '@angular/material/form-field';
import {MatInputModule} from '@angular/material/input';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {MatTooltipModule} from '@angular/material/tooltip';
import {MatDialogModule} from '@angular/material/dialog';
import {MatSnackBarModule} from '@angular/material/snack-bar';
import {MatChipsModule} from '@angular/material/chips';
import {MatSelectModule} from '@angular/material/select';
import {SharedModule} from '../common/shared.module';
import {AdminHomeComponent} from './admin-home/admin-home.component';
import {AdminDeprecatedModule} from './admin-deprecated.module';
import {AddUserDialogComponent} from './users-management/add-user-dialog.component';
import {CreateTeamWorkspaceDialogComponent} from './users-management/create-team-workspace-dialog.component';
import {AdminGroupAnalyticsComponent} from './admin-group-analytics/admin-group-analytics.component';
import {UnitPricesDialogComponent} from './admin-group-analytics/unit-prices-dialog.component';

@NgModule({
  declarations: [
    AdminLayoutComponent,
    UsersManagementComponent,
    UserFormComponent,
    AdminHomeComponent,
    AddUserDialogComponent,
    CreateTeamWorkspaceDialogComponent,
    AdminGroupAnalyticsComponent,
    UnitPricesDialogComponent,
  ],
  imports: [
    CommonModule,
    SharedModule,
    AdminRoutingModule,
    AdminDeprecatedModule,
    MatSidenavModule,
    MatListModule,
    MatPaginatorModule,
    MatSortModule,
    MatDialogModule,
    MatSnackBarModule,
    MatTooltipModule,
    MatToolbarModule,
    MatButtonModule,
    MatChipsModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    ReactiveFormsModule,
    MatSelectModule,
    MatProgressSpinnerModule,
    MatTableModule,
    FormsModule,
  ],
})
export class AdminModule {}
