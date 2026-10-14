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

import {Component, OnInit} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {
  AdminDashboardService,
  UserUsageCostRow,
  WorkspaceUsageCostResponse,
} from '../../services/admin/admin-dashboard.service';
import {WorkspaceService} from '../../services/workspace/workspace.service';
import {Workspace, WorkspaceType} from '../../common/models/workspace.model';
import {UnitPricesDialogComponent} from './unit-prices-dialog.component';

@Component({
  selector: 'app-admin-group-analytics',
  templateUrl: './admin-group-analytics.component.html',
  styleUrls: ['./admin-group-analytics.component.scss'],
})
export class AdminGroupAnalyticsComponent implements OnInit {
  isLoading = true;
  errorMessage: string | null = null;

  startDate = '';
  endDate = '';
  startCalendarDate: Date | null = null;
  endCalendarDate: Date | null = null;

  workspaces: Workspace[] = [];
  selectedWorkspaceId: number | null = null;

  usage: WorkspaceUsageCostResponse | null = null;
  userColumns = [
    'userEmail',
    'eventCount',
    'tokens',
    'media',
    'cost',
  ];

  constructor(
    private adminDashboardService: AdminDashboardService,
    private workspaceService: WorkspaceService,
    private dialog: MatDialog,
  ) {}

  ngOnInit(): void {
    const now = new Date();
    const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    const endOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0);

    this.startCalendarDate = startOfMonth;
    this.endCalendarDate = endOfMonth;
    this.startDate = this.formatDate(startOfMonth);
    this.endDate = this.formatDate(endOfMonth);

    this.loadWorkspaces();
  }

  onCalendarDateChange(event: {
    startDate: Date | null;
    endDate: Date | null;
  }): void {
    this.startCalendarDate = event.startDate;
    this.endCalendarDate = event.endDate;
    this.startDate = this.formatDate(this.startCalendarDate);
    this.endDate = this.formatDate(this.endCalendarDate);
    this.loadUsage();
  }

  onWorkspaceChange(): void {
    this.loadUsage();
  }

  get selectedWorkspace(): Workspace | undefined {
    return this.workspaces.find(w => w.id === this.selectedWorkspaceId);
  }

  get isPersonalWorkspace(): boolean {
    return this.selectedWorkspace?.type === WorkspaceType.PERSONAL;
  }

  get users(): UserUsageCostRow[] {
    return this.usage?.users || [];
  }

  get totalCost(): number {
    return this.usage?.totalEstimatedCostUsd || 0;
  }

  get totalEvents(): number {
    return this.users.reduce((sum, u) => sum + (u.eventCount || 0), 0);
  }

  get totalTokens(): number {
    return this.users.reduce(
      (sum, u) =>
        sum +
        (u.totalPromptTokens || 0) +
        (u.totalCandidatesTokens || 0) +
        (u.totalThoughtsTokens || 0),
      0,
    );
  }

  scopeLabel(scope: string | undefined): string {
    if (scope === WorkspaceType.PERSONAL) {
      return 'Personal';
    }
    if (scope === WorkspaceType.TEAM) {
      return 'Team';
    }
    return scope || '';
  }

  openUnitPricesDialog(): void {
    this.dialog.open(UnitPricesDialogComponent, {
      width: '960px',
      maxWidth: '95vw',
      maxHeight: '90vh',
      panelClass: 'unit-prices-dialog-panel',
    });
  }

  private loadWorkspaces(): void {
    this.isLoading = true;
    this.errorMessage = null;
    // List all non-personal workspaces platform-wide so each workspace's spend
    // can be tracked (team and admin). Personal workspaces are excluded since
    // per-user spend is already shown in the table below.
    this.workspaceService.getAllWorkspacesAdmin().subscribe({
      next: workspaces => {
        this.workspaces = (workspaces || [])
          .filter(w => w.type !== WorkspaceType.PERSONAL)
          .sort((a, b) => a.name.localeCompare(b.name));
        if (this.workspaces.length && this.selectedWorkspaceId == null) {
          this.selectedWorkspaceId = this.workspaces[0].id;
        }
        this.loadUsage();
      },
      error: err => {
        this.errorMessage =
          err?.message || 'Failed to load workspaces for usage analytics.';
        this.isLoading = false;
      },
    });
  }

  private loadUsage(): void {
    if (this.selectedWorkspaceId == null) {
      this.usage = null;
      this.isLoading = false;
      return;
    }

    this.isLoading = true;
    this.errorMessage = null;
    this.adminDashboardService
      .getUsageCostByWorkspace(
        this.selectedWorkspaceId,
        this.startDate,
        this.endDate,
      )
      .subscribe({
        next: usage => {
          this.usage = usage;
          this.isLoading = false;
        },
        error: err => {
          this.errorMessage =
            err?.error?.detail ||
            err?.message ||
            'Failed to load workspace usage.';
          this.isLoading = false;
        },
      });
  }

  private formatDate(date: Date | null): string {
    if (!date) {
      return '';
    }
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  }
}
