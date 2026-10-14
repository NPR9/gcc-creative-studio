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

import {
  Component,
  OnInit,
  OnDestroy,
  ViewChild,
  Inject,
  PLATFORM_ID,
} from '@angular/core';
import {MatTableDataSource} from '@angular/material/table';
import {MatSort} from '@angular/material/sort';
import {Subject} from 'rxjs';
import {debounceTime, distinctUntilChanged, takeUntil} from 'rxjs/operators';
import {isPlatformBrowser} from '@angular/common';
import {MatDialog} from '@angular/material/dialog';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Workspace, WorkspaceType} from '../../common/models/workspace.model';
import {WorkspaceMember} from '../../common/models/workspace-member.model';
import {WorkspaceService} from '../../services/workspace/workspace.service';
import {
  AddUserDialogComponent,
  AddUserDialogResult,
} from './add-user-dialog.component';
import {
  handleErrorSnackbar,
  handleSuccessSnackbar,
} from '../../utils/handleMessageSnackbar';
import {ConfirmationDialogComponent} from '../../common/components/confirmation-dialog/confirmation-dialog.component';
import {CreateTeamWorkspaceDialogComponent} from './create-team-workspace-dialog.component';

interface TreeNode {
  type: 'workspace' | 'member';
  level: number;
  expandable: boolean;
  isExpanded?: boolean;
  workspaceId?: number;
  workspaceName?: string;
  workspaceType?: WorkspaceType;
  memberCount?: number;
  member?: WorkspaceMember;
  parentWorkspaceId?: number;
}

@Component({
  selector: 'app-users-management',
  templateUrl: './users-management.component.html',
  styleUrls: ['./users-management.component.scss'],
})
export class UsersManagementComponent implements OnInit, OnDestroy {
  displayedColumns: string[] = [
    'expand',
    'name',
    'email',
    'createdAt',
    'actions',
  ];
  dataSource: MatTableDataSource<TreeNode> = new MatTableDataSource<TreeNode>();
  isLoading = true;
  errorLoadingUsers: string | null = null;
  workspaces: Workspace[] = [];
  expandedWorkspaceIds = new Set<number>();
  currentUserId: number | null = null;

  private filterSubject = new Subject<string>();
  private destroy$ = new Subject<void>();
  currentFilter = '';
  selectedWorkspaceId: number | null = null;

  readonly WorkspaceType = WorkspaceType;

  @ViewChild(MatSort) sort!: MatSort;

  constructor(
    private workspaceService: WorkspaceService,
    public dialog: MatDialog,
    private _snackBar: MatSnackBar,
    @Inject(PLATFORM_ID) private platformId: Object,
  ) {}

  ngOnInit(): void {
    if (isPlatformBrowser(this.platformId)) {
      const userDetailsStr = localStorage.getItem('USER_DETAILS');
      if (userDetailsStr) {
        this.currentUserId = JSON.parse(userDetailsStr).id || null;
      }
      this.loadWorkspaces();
    }

    this.filterSubject
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntil(this.destroy$))
      .subscribe(filterValue => {
        this.currentFilter = filterValue;
        this.applyFilterToTree();
      });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadWorkspaces(): void {
    this.isLoading = true;
    this.errorLoadingUsers = null;

    this.workspaceService.getAllWorkspacesAdmin().subscribe({
      next: (workspaces: Workspace[]) => {
        this.workspaces = workspaces.filter(
          ws =>
            ws.type === WorkspaceType.TEAM ||
            ws.type === WorkspaceType.ADMIN,
        );
        this.buildTreeData();
        this.isLoading = false;
      },
      error: (err: unknown) => {
        this.errorLoadingUsers = 'Failed to load workspaces and users.';
        console.error('Error loading workspaces:', err);
        this.isLoading = false;
      },
    });
  }

  buildTreeData(): void {
    this.applyFilterToTree();
  }

  toggleWorkspace(workspaceId: number): void {
    if (this.expandedWorkspaceIds.has(workspaceId)) {
      this.expandedWorkspaceIds.delete(workspaceId);
    } else {
      this.expandedWorkspaceIds.add(workspaceId);
    }
    this.buildTreeData();
  }

  isWorkspaceExpanded(workspaceId: number): boolean {
    return this.expandedWorkspaceIds.has(workspaceId);
  }

  applyFilter(event: Event): void {
    const filterValue = (event.target as HTMLInputElement).value;
    this.filterSubject.next(filterValue.trim().toLowerCase());
  }

  applyFilterToTree(): void {
    const visibleWorkspaces = this.selectedWorkspaceId
      ? this.workspaces.filter(ws => ws.id === this.selectedWorkspaceId)
      : this.workspaces;

    if (!this.currentFilter) {
      const treeNodes: TreeNode[] = [];
      for (const workspace of visibleWorkspaces) {
        treeNodes.push({
          type: 'workspace',
          level: 0,
          expandable: true,
          isExpanded: this.expandedWorkspaceIds.has(workspace.id),
          workspaceId: workspace.id,
          workspaceName: workspace.name,
          workspaceType: workspace.type,
          memberCount: workspace.members?.length || 0,
        });

        if (this.expandedWorkspaceIds.has(workspace.id) && workspace.members) {
          for (const member of workspace.members) {
            treeNodes.push({
              type: 'member',
              level: 1,
              expandable: false,
              member,
              parentWorkspaceId: workspace.id,
            });
          }
        }
      }
      this.dataSource.data = treeNodes;
      return;
    }

    const filter = this.currentFilter.toLowerCase();
    const treeNodes: TreeNode[] = [];

    for (const workspace of visibleWorkspaces) {
      const matchingMembers =
        workspace.members?.filter(
          member =>
            member.email.toLowerCase().includes(filter) ||
            (member.name || '').toLowerCase().includes(filter),
        ) || [];

      if (
        matchingMembers.length > 0 ||
        workspace.name.toLowerCase().includes(filter)
      ) {
        treeNodes.push({
          type: 'workspace',
          level: 0,
          expandable: true,
          isExpanded: true,
          workspaceId: workspace.id,
          workspaceName: workspace.name,
          workspaceType: workspace.type,
          memberCount: matchingMembers.length,
        });

        for (const member of matchingMembers) {
          treeNodes.push({
            type: 'member',
            level: 1,
            expandable: false,
            member,
            parentWorkspaceId: workspace.id,
          });
        }
      }
    }

    this.dataSource.data = treeNodes;
  }

  applyWorkspaceFilter(workspaceId: string): void {
    this.selectedWorkspaceId = workspaceId ? Number(workspaceId) : null;
    this.applyFilterToTree();
  }

  deleteWorkspace(workspaceId: number, workspaceName: string, workspaceType: WorkspaceType): void {
    if (workspaceType === WorkspaceType.PERSONAL) {
      handleErrorSnackbar(
        this._snackBar,
        {message: 'Personal workspaces cannot be deleted.'},
        'Delete workspace',
      );
      return;
    }

    if (workspaceType === WorkspaceType.ADMIN) {
      handleErrorSnackbar(
        this._snackBar,
        {message: 'The Administrators workspace cannot be deleted.'},
        'Delete workspace',
      );
      return;
    }

    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      width: '400px',
      data: {
        title: 'Confirm Workspace Deletion',
        message: `Are you sure you want to delete the team workspace "${workspaceName}"?`,
      },
    });

    dialogRef.afterClosed().subscribe((result: unknown) => {
      if (!result) return;

      this.isLoading = true;
      this.workspaceService.deleteTeamWorkspace(workspaceId).subscribe({
        next: () => {
          handleSuccessSnackbar(
            this._snackBar,
            `Workspace "${workspaceName}" deleted successfully!`,
          );
          this.expandedWorkspaceIds.delete(workspaceId);
          this.loadWorkspaces();
        },
        error: err => {
          handleErrorSnackbar(this._snackBar, err, 'Delete workspace');
          this.isLoading = false;
        },
      });
    });
  }

  openCreateTeamWorkspaceDialog(): void {
    const dialogRef = this.dialog.open(CreateTeamWorkspaceDialogComponent, {
      width: '500px',
    });

    dialogRef.afterClosed().subscribe((result: {name: string} | undefined) => {
      if (result?.name) {
        this.isLoading = true;
        this.workspaceService.createTeamWorkspaceAdmin(result.name).subscribe({
          next: created => {
            handleSuccessSnackbar(
              this._snackBar,
              `Team workspace "${created.name}" created successfully!`,
            );
            this.expandedWorkspaceIds.add(created.id);
            this.loadWorkspaces();
          },
          error: err => {
            handleErrorSnackbar(this._snackBar, err, 'Failed to create workspace');
            this.isLoading = false;
          },
        });
      }
    });
  }

  openAddUserDialog(): void {
    const teamWorkspaces = this.workspaces.filter(
      ws => ws.type === WorkspaceType.TEAM,
    );
    const dialogRef = this.dialog.open(AddUserDialogComponent, {
      width: '500px',
      data: {workspaces: teamWorkspaces},
    });

    dialogRef.afterClosed().subscribe((result: AddUserDialogResult | undefined) => {
      if (!result) return;

      this.isLoading = true;
      const request$ = result.isAdmin
        ? this.workspaceService.addAdminUserByEmail(result.email)
        : this.workspaceService.addUserToWorkspaceByEmail(
            result.workspaceId!,
            result.email,
          );

      request$.subscribe({
        next: () => {
          handleSuccessSnackbar(
            this._snackBar,
            result.isAdmin
              ? 'Admin user added successfully!'
              : 'User added to workspace successfully!',
          );
          this.loadWorkspaces();
        },
        error: err => {
          this.isLoading = false;
          handleErrorSnackbar(this._snackBar, err, 'Add user');
        },
      });
    });
  }

  removeMemberFromWorkspace(node: TreeNode): void {
    if (!node.member || !node.parentWorkspaceId) return;

    const dialogRef = this.dialog.open(ConfirmationDialogComponent, {
      width: '400px',
      data: {
        title: 'Remove User',
        message: `Remove ${node.member.email} from this workspace?`,
      },
    });

    dialogRef.afterClosed().subscribe((confirmed: unknown) => {
      if (!confirmed) return;

      this.workspaceService
        .removeUserFromWorkspace(node.parentWorkspaceId!, node.member!.userId)
        .subscribe({
          next: () => {
            handleSuccessSnackbar(
              this._snackBar,
              'Member removed from workspace.',
            );
            this.loadWorkspaces();
          },
          error: err => handleErrorSnackbar(this._snackBar, err, 'Remove member'),
        });
    });
  }
}
