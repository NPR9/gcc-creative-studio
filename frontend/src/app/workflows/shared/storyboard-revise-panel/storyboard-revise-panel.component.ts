/**
 * Copyright 2026 Google LLC
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

import {Component, Input, OnChanges, OnDestroy} from '@angular/core';
import {firstValueFrom} from 'rxjs';
import {GalleryService} from '../../../gallery/gallery.service';
import {WorkspaceStateService} from '../../../services/workspace/workspace-state.service';
import {
  StoryboardPendingJob,
  StoryboardRevisionResult,
  WorkflowService,
} from '../../workflow.service';

interface FrameRow {
  shotNumber: number;
  sceneTitle: string;
  action: string;
  mediaId: number | null;
  note: string;
  pending: boolean;
}

// Poll the gallery every 4s for up to 4 minutes per pending image.
const POLL_INTERVAL_MS = 4000;
const MAX_POLLS = 60;

/**
 * Storyboard panel on a finished run.
 *
 * - Plan awaiting approval: the requester reviews the text plan, can ask
 *   for plan changes, then approves; character sheets are drawn first,
 *   then every frame.
 * - Drawn board: notes on individual frames revise only those frames.
 *
 * Every backend call returns in seconds (Firebase Hosting cuts requests at
 * 60s); images render in the background and are polled here.
 */
@Component({
  selector: 'app-storyboard-revise-panel',
  templateUrl: './storyboard-revise-panel.component.html',
})
export class StoryboardRevisePanelComponent implements OnChanges, OnDestroy {
  @Input() shotList: any = null;
  @Input() storyboardText = '';

  board: any = null;
  boardText = '';
  frames: FrameRow[] = [];
  generalNote = '';
  isOpen = false;
  isBusy = false;
  busyLabel = '';
  revisionCount = 0;
  errorMessage: string | null = null;
  frameErrors: string[] = [];
  copied = false;
  urls = new Map<number, string>();
  pendingCount = 0;
  private timers: ReturnType<typeof setTimeout>[] = [];
  private destroyed = false;

  constructor(
    private workflowService: WorkflowService,
    private workspaceStateService: WorkspaceStateService,
    private galleryService: GalleryService,
  ) {}

  ngOnChanges(): void {
    if (this.shotList && !this.board) {
      this.setBoard(this.shotList, this.storyboardText);
      this.isOpen = this.awaitingApproval;
    }
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.timers.forEach(t => clearTimeout(t));
  }

  get awaitingApproval(): boolean {
    return !!this.board?.awaiting_approval;
  }

  get hasNotes(): boolean {
    return (
      this.generalNote.trim().length > 0 ||
      this.frames.some(f => f.note.trim().length > 0)
    );
  }

  get canAct(): boolean {
    return !this.isBusy && this.pendingCount === 0;
  }

  frameUrl(frame: FrameRow): string {
    return frame.mediaId ? this.urls.get(frame.mediaId) || '' : '';
  }

  /** Plan changes before approval, or frame changes after drawing. */
  revise(): void {
    const workspaceId = this.workspaceId();
    if (!this.hasNotes || !this.canAct || !workspaceId) return;
    this.startBusy(
      this.awaitingApproval ? 'Updating plan...' : 'Planning changes...',
    );

    this.workflowService
      .reviseStoryboard({
        workspace_id: workspaceId,
        shot_list: this.board,
        change_notes: this.composeNotes(),
        settings: this.board?.settings ?? {},
        plan_only: this.awaitingApproval,
      })
      .subscribe({
        next: (result: StoryboardRevisionResult) => {
          this.isBusy = false;
          this.revisionCount++;
          this.generalNote = '';
          this.setBoard(result.shot_list, result.storyboard_text);
          void this.trackPending(result.pending ?? []);
        },
        error: err => this.fail(err, 'Revision failed. Please try again.'),
      });
  }

  /** Approve the plan: draw character sheets, then every frame. */
  async approve(): Promise<void> {
    const workspaceId = this.workspaceId();
    if (!this.awaitingApproval || !this.canAct || !workspaceId) return;
    const settings = this.board?.settings ?? {};

    try {
      const wantsSheets =
        settings.character_sheets !== false &&
        (this.board?.characters?.length ?? 0) > 0;
      if (wantsSheets) {
        this.startBusy('Drawing character sheets...');
        const sheets = await firstValueFrom(
          this.workflowService.renderStoryboard({
            workspace_id: workspaceId,
            shot_list: this.board,
            phase: 'sheets',
            settings,
          }),
        );
        this.setBoard(sheets.shot_list, sheets.storyboard_text);
        await this.trackPending(sheets.pending ?? []);
      }

      this.startBusy('Drawing frames...');
      const drawn = await firstValueFrom(
        this.workflowService.renderStoryboard({
          workspace_id: workspaceId,
          shot_list: this.board,
          phase: 'frames',
          settings,
        }),
      );
      this.isBusy = false;
      this.setBoard(drawn.shot_list, drawn.storyboard_text);
      void this.trackPending(drawn.pending ?? []);
    } catch (err) {
      this.fail(err, 'Drawing failed. Please try again.');
    }
  }

  copyBoard(): void {
    if (!this.boardText || !navigator.clipboard) return;
    void navigator.clipboard.writeText(this.boardText).then(() => {
      this.copied = true;
      setTimeout(() => (this.copied = false), 2000);
    });
  }

  private workspaceId(): number | null {
    const id = this.workspaceStateService.getActiveWorkspaceId();
    if (!id) this.errorMessage = 'Select a workspace first.';
    return id;
  }

  private startBusy(label: string): void {
    this.isBusy = true;
    this.busyLabel = label;
    this.errorMessage = null;
  }

  private fail(err: any, fallback: string): void {
    this.isBusy = false;
    this.errorMessage = err?.error?.detail || fallback;
  }

  private composeNotes(): string {
    const lines: string[] = [];
    if (this.generalNote.trim()) lines.push(this.generalNote.trim());
    this.frames
      .filter(f => f.note.trim())
      .forEach(f => lines.push(`Frame ${f.shotNumber}: ${f.note.trim()}`));
    return lines.join('\n');
  }

  private setBoard(board: any, text: string): void {
    this.board = board;
    this.boardText = text || this.boardText;
    this.frameErrors = board?.frame_errors ?? [];
    this.frames = (board?.scenes ?? []).flatMap((scene: any) =>
      (scene.shots ?? []).map((shot: any) => ({
        shotNumber: shot.shot_number,
        sceneTitle: scene.title,
        action: shot.action,
        mediaId: shot.frame_media_id ?? null,
        note: '',
        pending: false,
      })),
    );
    this.loadUrls();
  }

  /**
   * Images render in the background. Poll each one; when one fails, put
   * the previous image back so the board never has a hole. Resolves when
   * every job has finished.
   */
  private trackPending(jobs: StoryboardPendingJob[]): Promise<void> {
    return Promise.all(
      jobs.map(job => {
        const frame =
          job.kind === 'frame'
            ? this.frames.find(f => f.shotNumber === job.shot_number)
            : undefined;
        if (frame) frame.pending = true;
        this.pendingCount++;
        return new Promise<void>(resolve => this.poll(job, frame, 0, resolve));
      }),
    ).then(() => undefined);
  }

  private poll(
    job: StoryboardPendingJob,
    frame: FrameRow | undefined,
    attempt: number,
    done: () => void,
  ): void {
    if (this.destroyed) return done();
    const timer = setTimeout(() => {
      this.galleryService.getMedia(job.media_id).subscribe({
        next: item => {
          const status = (item?.status || '').toLowerCase();
          if (status === 'completed') {
            const url = item?.presignedUrls?.[0];
            if (url) this.urls.set(job.media_id, url);
            this.finish(frame, done);
          } else if (status === 'failed' || attempt >= MAX_POLLS) {
            this.revert(job, frame, done);
          } else {
            this.poll(job, frame, attempt + 1, done);
          }
        },
        error: () =>
          attempt >= MAX_POLLS
            ? this.revert(job, frame, done)
            : this.poll(job, frame, attempt + 1, done),
      });
    }, POLL_INTERVAL_MS);
    this.timers.push(timer);
  }

  private revert(
    job: StoryboardPendingJob,
    frame: FrameRow | undefined,
    done: () => void,
  ): void {
    const previous = job.previous_media_id ?? null;
    if (job.kind === 'frame') {
      this.board?.scenes?.forEach((scene: any) =>
        scene.shots?.forEach((shot: any) => {
          if (shot.shot_number === job.shot_number) {
            shot.frame_media_id = previous;
          }
        }),
      );
      if (frame) frame.mediaId = previous;
      this.frameErrors = [
        ...this.frameErrors,
        `Frame ${job.shot_number}: new image failed` +
          (previous ? ', kept the previous one.' : '.'),
      ];
    } else {
      this.board?.characters?.forEach((c: any) => {
        if (c.key === job.key) c.character_sheet_id = previous;
      });
      this.frameErrors = [
        ...this.frameErrors,
        `Character sheet ${job.key}: image failed.`,
      ];
    }
    this.finish(frame, done);
    this.loadUrls();
  }

  private finish(frame: FrameRow | undefined, done: () => void): void {
    if (frame) frame.pending = false;
    this.pendingCount = Math.max(0, this.pendingCount - 1);
    done();
  }

  private loadUrls(): void {
    this.frames
      .filter(f => !f.pending)
      .map(f => f.mediaId)
      .filter((id): id is number => !!id && !this.urls.has(id))
      .forEach(id =>
        this.galleryService.getMedia(id).subscribe({
          next: item => {
            const url = item?.presignedUrls?.[0];
            if (url) this.urls.set(id, url);
          },
          error: err => console.error(`Failed to load frame ${id}`, err),
        }),
      );
  }
}
