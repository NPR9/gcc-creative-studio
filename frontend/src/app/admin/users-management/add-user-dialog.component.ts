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

import {Component, Inject} from '@angular/core';
import {FormBuilder, Validators} from '@angular/forms';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material/dialog';
import {Workspace} from '../../common/models/workspace.model';

export interface AddUserDialogData {
  workspaces: Workspace[];
}

export interface AddUserDialogResult {
  email: string;
  isAdmin: boolean;
  workspaceId?: number;
}

@Component({
  selector: 'app-add-user-dialog',
  template: `
    <h2 mat-dialog-title>Add User</h2>

    <form [formGroup]="form" (ngSubmit)="submit()" class="p-4 pt-0">
      <div class="grid gap-4">
        <mat-form-field appearance="outline">
          <mat-label>Email</mat-label>
          <input matInput type="email" formControlName="email" cdkFocusInitial />
          <mat-error *ngIf="form.get('email')?.hasError('required')">
            Email is required
          </mat-error>
          <mat-error *ngIf="form.get('email')?.hasError('email')">
            Enter a valid email
          </mat-error>
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>User Type</mat-label>
          <mat-select formControlName="userType">
            <mat-option value="user">Regular User</mat-option>
            <mat-option value="admin">Admin</mat-option>
          </mat-select>
        </mat-form-field>

        <mat-form-field appearance="outline" *ngIf="!isAdminSelected">
          <mat-label>Team Workspace</mat-label>
          <mat-select formControlName="workspaceId">
            <mat-option
              *ngFor="let workspace of data.workspaces"
              [value]="workspace.id"
            >
              {{ workspace.name }}
            </mat-option>
          </mat-select>
          <mat-error *ngIf="form.get('workspaceId')?.hasError('required')">
            Workspace is required
          </mat-error>
        </mat-form-field>

        <p class="text-sm text-gray-400 mt-2" *ngIf="isAdminSelected">
          Admins get access to all workspaces automatically. A personal workspace
          will be created using their email.
        </p>
        <p class="text-sm text-gray-400 mt-2" *ngIf="!isAdminSelected">
          User will be added to the team workspace and receive a personal
          workspace.
        </p>
      </div>

      <div mat-dialog-actions align="end" class="mt-4">
        <button mat-button type="button" (click)="dialogRef.close()">Cancel</button>
        <button mat-flat-button color="primary" type="submit" [disabled]="form.invalid">
          Add User
        </button>
      </div>
    </form>
  `,
})
export class AddUserDialogComponent {
  form;

  constructor(
    private fb: FormBuilder,
    public dialogRef: MatDialogRef<AddUserDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: AddUserDialogData,
  ) {
    this.form = this.fb.group({
      email: ['', [Validators.required, Validators.email]],
      userType: ['user', Validators.required],
      workspaceId: [null as number | null, Validators.required],
    });

    this.form.get('userType')?.valueChanges.subscribe(userType => {
      const workspaceControl = this.form.get('workspaceId');
      if (userType === 'admin') {
        workspaceControl?.clearValidators();
        workspaceControl?.setValue(null);
      } else {
        workspaceControl?.setValidators(Validators.required);
      }
      workspaceControl?.updateValueAndValidity();
    });
  }

  get isAdminSelected(): boolean {
    return this.form.get('userType')?.value === 'admin';
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const value = this.form.getRawValue();
    const isAdmin = value.userType === 'admin';
    this.dialogRef.close({
      email: (value.email || '').trim().toLowerCase(),
      isAdmin,
      workspaceId: isAdmin ? undefined : Number(value.workspaceId),
    } as AddUserDialogResult);
  }
}
