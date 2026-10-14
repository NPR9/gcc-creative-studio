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

import {Injectable} from '@angular/core';
import {HttpClient, HttpParams} from '@angular/common/http';
import {Observable} from 'rxjs';
import {environment} from '../../../environments/environment';
import {WorkspaceRole} from '../../common/models/workspace-member.model';
import {Workspace} from '../../common/models/workspace.model';
import {WorkspaceMember} from '../../common/models/workspace-member.model';

export interface AddUserByEmailResponse {
  provisioningStatus: string;
  createdNewUser: boolean;
  userId: number;
  email: string;
  workspace?: Workspace;
}

@Injectable({
  providedIn: 'root',
})
export class WorkspaceService {
  private apiUrl = `${environment.backendURL}/workspaces`;
  private adminApiUrl = `${environment.backendURL}/admin/workspaces`;

  constructor(private http: HttpClient) {}

  getWorkspaces(): Observable<Workspace[]> {
    return this.http.get<Workspace[]>(this.apiUrl);
  }

  getSwitcherWorkspaces(): Observable<Workspace[]> {
    return this.http.get<Workspace[]>(`${this.apiUrl}/switcher`);
  }

  getAssignedWorkspace(): Observable<Workspace | null> {
    return this.http.get<Workspace | null>(`${this.apiUrl}/assigned`);
  }

  getWorkspaceMembers(workspaceId: number): Observable<WorkspaceMember[]> {
    return this.http.get<WorkspaceMember[]>(
      `${this.apiUrl}/${workspaceId}/members`,
    );
  }

  createWorkspace(name: string): Observable<Workspace> {
    return this.http.post<Workspace>(this.apiUrl, {name});
  }

  inviteUser(
    workspaceId: number,
    email: string,
    role: WorkspaceRole,
  ): Observable<void> {
    return this.http.post<void>(`${this.apiUrl}/${workspaceId}/invites`, {
      email,
      role,
    });
  }

  getAllWorkspacesAdmin(): Observable<Workspace[]> {
    return this.http.get<Workspace[]>(this.adminApiUrl);
  }

  createTeamWorkspaceAdmin(name: string): Observable<Workspace> {
    const params = new HttpParams().set('name', name);
    return this.http.post<Workspace>(this.adminApiUrl, null, {params});
  }

  addUserToWorkspaceByEmail(
    workspaceId: number,
    email: string,
  ): Observable<AddUserByEmailResponse> {
    return this.http.post<AddUserByEmailResponse>(
      `${this.adminApiUrl}/${workspaceId}/users/by-email`,
      {email},
    );
  }

  addAdminUserByEmail(email: string): Observable<AddUserByEmailResponse> {
    return this.http.post<AddUserByEmailResponse>(
      `${environment.backendURL}/admin/users/by-email`,
      {email},
    );
  }

  removeUserFromWorkspace(
    workspaceId: number,
    userId: number,
  ): Observable<{message: string}> {
    return this.http.delete<{message: string}>(
      `${this.adminApiUrl}/${workspaceId}/users/${userId}`,
    );
  }

  deleteTeamWorkspace(workspaceId: number): Observable<{message: string}> {
    return this.http.delete<{message: string}>(
      `${this.adminApiUrl}/${workspaceId}`,
    );
  }
}
