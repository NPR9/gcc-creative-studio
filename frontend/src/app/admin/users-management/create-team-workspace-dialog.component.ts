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

import {Component} from '@angular/core';
import {FormBuilder, Validators} from '@angular/forms';
import {MatDialogRef} from '@angular/material/dialog';

@Component({
  selector: 'app-create-team-workspace-dialog',
  template: `
    <h2 mat-dialog-title>Create Team Workspace</h2>
    <form [formGroup]="form" (ngSubmit)="submit()" class="p-4 pt-0">
      <mat-form-field appearance="outline" class="w-full">
        <mat-label>Workspace Name</mat-label>
        <input matInput formControlName="name" cdkFocusInitial />
        <mat-error *ngIf="form.get('name')?.hasError('required')">
          Name is required
        </mat-error>
      </mat-form-field>
      <div mat-dialog-actions align="end" class="mt-4">
        <button mat-button type="button" (click)="dialogRef.close()">Cancel</button>
        <button mat-flat-button color="primary" type="submit" [disabled]="form.invalid">
          Create
        </button>
      </div>
    </form>
  `,
})
export class CreateTeamWorkspaceDialogComponent {
  form;

  constructor(
    private fb: FormBuilder,
    public dialogRef: MatDialogRef<CreateTeamWorkspaceDialogComponent>,
  ) {
    this.form = this.fb.group({
      name: ['', Validators.required],
    });
  }

  submit(): void {
    if (this.form.invalid) return;
    const name = this.form.get('name')?.value?.trim();
    if (!name) return;
    this.dialogRef.close({name});
  }
}
