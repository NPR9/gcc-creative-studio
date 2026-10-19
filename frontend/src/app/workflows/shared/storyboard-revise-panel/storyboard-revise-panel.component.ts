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
 * Lets the requester change individual frames of a finished storyboard.
 * Only frames with a note (or touched by the general note) are edited or
 * redrawn; the rest keep their images.
 */
@Component({
  selector: 'app-storyboard-revise-panel',
  templateUrl: './storyboard-revise-panel.component.html',
})
export class StoryboardRevisePanelComponent implements OnChanges, OnDestroy {
  @Input() shotList: any = null;

  board: any = null;
  boardText = '';
  frames: FrameRow[] = [];
  generalNote = '';
  isOpen = false;
  isRevising = false;
  revisionCount = 0;
  errorMessage: string | null = null;
  frameErrors: string[] = [];
  copied = false;
  urls = new Map<number, string>();
  pendingCount = 0;
  private timers: ReturnType<typeof setTimeout>[] = [];

  constructor(
    private workflowService: WorkflowService,
    private workspaceStateService: WorkspaceStateService,
    private galleryService: GalleryService,
  ) {}

  ngOnChanges(): void {
    if (this.shotList && !this.board) {
      this.setBoard(this.shotList, '');
    }
  }

  ngOnDestroy(): void {
    this.timers.forEach(t => clearTimeout(t));
  }

  get hasNotes(): boolean {
    return (
      this.generalNote.trim().length > 0 ||
      this.frames.some(f => f.note.trim().length > 0)
    );
  }

  frameUrl(frame: FrameRow): string {
    return frame.mediaId ? this.urls.get(frame.mediaId) || '' : '';
  }

  revise(): void {
    if (!this.hasNotes || this.isRevising || this.pendingCount > 0) return;
    const workspaceId = this.workspaceStateService.getActiveWorkspaceId();
    if (!workspaceId) {
      this.errorMessage = 'Select a workspace first.';
      return;
    }
    this.isRevising = true;
    this.errorMessage = null;

    this.workflowService
      .reviseStoryboard({
        workspace_id: workspaceId,
        shot_list: this.board,
        change_notes: this.composeNotes(),
        settings: this.board?.settings ?? {},
      })
      .subscribe({
        next: (result: StoryboardRevisionResult) => {
          this.isRevising = false;
          this.revisionCount++;
          this.generalNote = '';
          this.setBoard(result.shot_list, result.storyboard_text);
          this.trackPending(result.pending ?? []);
        },
        error: err => {
          this.isRevising = false;
          this.errorMessage =
            err?.error?.detail || 'Revision failed. Please try again.';
        },
      });
  }

  copyBoard(): void {
    if (!this.boardText || !navigator.clipboard) return;
    void navigator.clipboard.writeText(this.boardText).then(() => {
      this.copied = true;
      setTimeout(() => (this.copied = false), 2000);
    });
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
    this.boardText = text;
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
   * Changed frames render in the background. Poll each one; when it fails,
   * put the previous image back so the board never has a hole.
   */
  private trackPending(jobs: StoryboardPendingJob[]): void {
    jobs.forEach(job => {
      const frame =
        job.kind === 'frame'
          ? this.frames.find(f => f.shotNumber === job.shot_number)
          : undefined;
      if (frame) frame.pending = true;
      this.pendingCount++;
      this.poll(job, frame, 0);
    });
  }

  private poll(
    job: StoryboardPendingJob,
    frame: FrameRow | undefined,
    attempt: number,
  ): void {
    const timer = setTimeout(() => {
      this.galleryService.getMedia(job.media_id).subscribe({
        next: item => {
          const status = (item?.status || '').toLowerCase();
          if (status === 'completed') {
            const url = item?.presignedUrls?.[0];
            if (url) this.urls.set(job.media_id, url);
            this.finish(frame);
          } else if (status === 'failed' || attempt >= MAX_POLLS) {
            this.revert(job, frame);
          } else {
            this.poll(job, frame, attempt + 1);
          }
        },
        error: () =>
          attempt >= MAX_POLLS
            ? this.revert(job, frame)
            : this.poll(job, frame, attempt + 1),
      });
    }, POLL_INTERVAL_MS);
    this.timers.push(timer);
  }

  private revert(job: StoryboardPendingJob, frame: FrameRow | undefined): void {
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
        `Character sheet ${job.key}: new image failed.`,
      ];
    }
    this.finish(frame);
    this.loadUrls();
  }

  private finish(frame: FrameRow | undefined): void {
    if (frame) frame.pending = false;
    this.pendingCount = Math.max(0, this.pendingCount - 1);
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
