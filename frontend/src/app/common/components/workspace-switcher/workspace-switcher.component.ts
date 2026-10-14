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

import {Component, OnInit, Inject, PLATFORM_ID} from '@angular/core';
import {isPlatformBrowser} from '@angular/common';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {ActivatedRoute} from '@angular/router';
import {map, switchMap} from 'rxjs';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {WorkspaceService} from '../../../services/workspace/workspace.service';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../../utils/handleMessageSnackbar';
import {JobStatus} from '../../models/media-item.model';
import {UserModel, UserRolesEnum} from '../../models/user.model';
import {Workspace, WorkspaceType} from '../../models/workspace.model';
import {BrandGuidelineService} from '../../services/brand-guideline/brand-guideline.service';
import {UserService} from '../../services/user.service';
import {environment} from '../../../../environments/environment';
import {
  BrandGuidelineDialogComponent,
  BrandGuidelineDialogData,
} from '../brand-guideline-dialog/brand-guideline-dialog.component';
import {ConfirmationDialogComponent} from '../confirmation-dialog/confirmation-dialog.component';
import {CreateWorkspaceModalComponent} from '../create-workspace-modal/create-workspace-modal.component';
import {
  InviteUserData,
  InviteUserModalComponent,
} from '../invite-user-modal/invite-user-modal.component';

@Component({
  selector: 'app-workspace-switcher',
  templateUrl: './workspace-switcher.component.html',
  styleUrls: ['./workspace-switcher.component.scss'],
})
export class WorkspaceSwitcherComponent implements OnInit {
  workspaces: Workspace[] = [];
  selectableWorkspaces: Workspace[] = [];
  activeWorkspaceId: number | null = null;
  activeWorkspace: Workspace | null = null;
  assignedSharedWorkspace: Workspace | null = null;
  currentUser: UserModel | null;
  readonly JobStatus = JobStatus;
  public WorkspaceType = WorkspaceType;

  isBrowser: boolean;

  constructor(
    private workspaceService: WorkspaceService,
    private workspaceStateService: WorkspaceStateService,
    public brandGuidelineService: BrandGuidelineService,
    private userService: UserService,
    private route: ActivatedRoute,
    public dialog: MatDialog,
    private snackBar: MatSnackBar,
    @Inject(PLATFORM_ID) platformId: Object,
  ) {
    this.currentUser = this.userService.getUserDetails();
    this.isBrowser = isPlatformBrowser(platformId);
  }

  ngOnInit(): void {
    this.loadWorkspaceContext();
    this.workspaceStateService.activeWorkspaceId$.subscribe(id => {
      // Ensure we handle both string (from legacy/url) and number types safely if needed,
      // but ideally workspaceStateService should also be consistent.
      // Assuming workspaceStateService might still emit strings if not updated, let's cast or parse if needed.
      // For now, let's assume strict number typing is propagated.
      // Actually, workspaceStateService might need checking too.
      // Let's assume id is number here based on the goal.
      this.activeWorkspaceId = typeof id === 'string' ? parseInt(id, 10) : id;
      this.activeWorkspace =
        this.workspaces.find(w => w.id === this.activeWorkspaceId) || null;
    });

    this.brandGuidelineService.activeBrandGuidelineJob$.subscribe(job => {
      if (job) {
        if (job.status === JobStatus.COMPLETED) {
          handleSuccessSnackbar(
            this.snackBar,
            'Brand Guidelines processed successfully!',
          );
          // Reset the job so the spinner disappears and the button is re-enabled.
          this.brandGuidelineService.clearActiveJob();
        } else if (job.status === JobStatus.FAILED) {
          handleErrorSnackbar(
            this.snackBar,
            {
              message: job.errorMessage || 'Brand Guideline processing failed.',
            },
            'Processing Error',
          );
          this.brandGuidelineService.clearActiveJob();
        }
      }
    });
  }

  loadWorkspaceContext(): void {
    this.workspaceService.getSwitcherWorkspaces().subscribe({
      next: workspaces => {
        this.setWorkspaceCollections(workspaces);
      },
      error: error => {
        handleErrorSnackbar(this.snackBar, error, 'Could not load workspaces');
      },
    });
    this.workspaceService.getAssignedWorkspace().subscribe({
      next: workspace => {
        this.assignedSharedWorkspace = workspace;
      },
      error: () => {
        this.assignedSharedWorkspace = null;
      },
    });
  }

  private findPersonalWorkspace(): Workspace | null {
    if (!this.currentUser) return null;
    return (
      this.workspaces.find(
        w =>
          w.type === WorkspaceType.PERSONAL &&
          w.ownerId === this.currentUser!.id,
      ) ||
      this.workspaces.find(w => w.type === WorkspaceType.PERSONAL) ||
      null
    );
  }

  private setWorkspaceCollections(workspaces: Workspace[]): void {
    this.workspaces = workspaces;
    this.selectableWorkspaces = workspaces;
    this.initializeActiveWorkspace();
  }

  initializeActiveWorkspace(): void {
    if (!this.isBrowser) return;

    // Generation and the personal gallery are always pinned to the user's
    // personal workspace. Shared assets are viewed via the Shared Gallery.
    const personalWorkspace = this.findPersonalWorkspace();
    if (personalWorkspace) {
      this.setActiveWorkspace(personalWorkspace.id);
      return;
    }

    if (this.selectableWorkspaces.length > 0) {
      this.setActiveWorkspace(this.selectableWorkspaces[0].id);
    } else {
      this.activeWorkspace = null;
      this.workspaceStateService.setActiveWorkspaceId(null);
      if (this.isBrowser) {
        localStorage.removeItem('activeWorkspaceId');
      }
    }
  }

  setActiveWorkspace(workspaceId: number | null): void {
    // We might need to cast to any if workspaceStateService expects string,
    // but we should check that service too. For now, let's assume we pass number.
    this.workspaceStateService.setActiveWorkspaceId(workspaceId);
    this.activeWorkspace =
      this.workspaces.find(w => w.id === workspaceId) || null;
    this.brandGuidelineService.clearCache();

    if (this.isBrowser) {
      if (workspaceId) {
        localStorage.setItem('activeWorkspaceId', workspaceId.toString());
      } else {
        localStorage.removeItem('activeWorkspaceId');
      }
    }
  }

  get canAccessBrandGuidelines(): boolean {
    if (!this.currentUser || !this.activeWorkspace) return false;

    const isAdmin = !!this.currentUser.roles?.includes(UserRolesEnum.ADMIN);
    const isWorkspaceAdmin = this.activeWorkspace.members?.some(
      m => m.userId === this.currentUser!.id && m.role === 'admin',
    );
    const isOwner = this.currentUser.id === this.activeWorkspace.ownerId;
    return isAdmin || isWorkspaceAdmin || isOwner;
  }

  get canPerformEditActionsOnBrandGuidelines(): boolean {
    if (!this.currentUser || !this.activeWorkspace) return false;
    const isAdmin = !!this.currentUser.roles?.includes(UserRolesEnum.ADMIN);
    const isWorkspaceAdmin = this.activeWorkspace.members?.some(
      m => m.userId === this.currentUser!.id && m.role === 'admin',
    );
    const isOwner = this.currentUser.id === this.activeWorkspace.ownerId;
    return isAdmin || isWorkspaceAdmin || isOwner;
  }

  openBrandGuidelinesDialog(event: MouseEvent): void {
    event.stopPropagation();
    if (!this.activeWorkspaceId) return;
    const workspaceId = this.activeWorkspaceId;

    this.brandGuidelineService
      .getBrandGuidelineForWorkspace(workspaceId)
      .pipe(
        switchMap(guideline => {
          const dialogRef = this.dialog.open<
            BrandGuidelineDialogComponent,
            BrandGuidelineDialogData
          >(BrandGuidelineDialogComponent, {
            width: '800px',
            maxWidth: '90vw',
            panelClass: 'brand-guideline-dialog',
            data: {
              workspaceId: workspaceId,
              guideline,
              canEdit: this.canPerformEditActionsOnBrandGuidelines,
            },
          });
          return dialogRef
            .afterClosed()
            .pipe(map(result => ({result, guideline})));
        }),
      )
      .subscribe(({result, guideline}) => {
        if (!result) {
          return; // Dialog was closed without action
        }

        // Handle Deletion
        if (result.delete && guideline?.id) {
          const confirmationDialogRef = this.dialog.open(
            ConfirmationDialogComponent,
            {
              data: {
                title: 'Delete Brand Guideline?',
                message:
                  'Are you sure you want to delete the brand guideline for this workspace? This action cannot be undone.',
              },
            },
          );

          confirmationDialogRef.afterClosed().subscribe(confirmed => {
            if (confirmed) {
              this.brandGuidelineService
                .deleteBrandGuideline(guideline.id)
                .subscribe({
                  next: () => {
                    handleSuccessSnackbar(
                      this.snackBar,
                      'Brand Guideline deleted.',
                    );
                  },
                  error: error =>
                    handleErrorSnackbar(
                      this.snackBar,
                      error,
                      'Could not delete brand guideline.',
                    ),
                });
            }
          });
        } else if (result.name && result.file && workspaceId) {
          // 1. Immediately show spinner and show initial snackbar
          this.brandGuidelineService.setProcessingState();
          handleSuccessSnackbar(
            this.snackBar,
            'Uploading file, please keep this window open...',
          );

          // 2. Start the upload process
          this.brandGuidelineService
            .createBrandGuideline(workspaceId, result.file, result.name)
            .subscribe({
              next: () => {
                // 3. On success, show the "processing" snackbar
                handleSuccessSnackbar(
                  this.snackBar,
                  'File uploaded! We will process it and notify you upon completion. You can close this window or navigate away!',
                );
              },
              error: error => {
                // On error, clear the job so the spinner disappears
                this.brandGuidelineService.clearActiveJob();
                handleErrorSnackbar(this.snackBar, error, 'Upload failed');
              },
            });
        }
      });
  }

  openFeedbackForm(event: MouseEvent): void {
    event.stopPropagation();
    if (this.isBrowser) {
      window.open(
        'https://docs.google.com/forms/d/e/1FAIpQLSceWvu7G354h-dTbOGvNGEraEjcUAgPE300WNY5qr-WJbh3Eg/viewform',
        '_blank',
      );
    }
  }

  getBackendUrl(): string {
    const backendUrl = localStorage.getItem('backend_url') || environment.backendURL.replace(/\/api$/, '');
    return backendUrl;
  }
}
