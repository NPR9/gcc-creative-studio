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

import {Component, NgZone, Inject, PLATFORM_ID, OnInit} from '@angular/core';
import {Router} from '@angular/router';
import {AuthService} from './../common/services/auth.service';
import {MatSnackBar} from '@angular/material/snack-bar';
import {handleErrorSnackbar} from '../utils/handleMessageSnackbar';
import {environment} from '../../environments/environment';
import {isPlatformBrowser} from '@angular/common';

const HOME_ROUTE = '/';

@Component({
  selector: 'app-login',
  templateUrl: './login.component.html',
  styleUrls: ['./login.component.scss'],
})
export class LoginComponent implements OnInit {
  loader = false;
  isBrowser: boolean;
  isLocal = environment.isLocal;
  localUserEmail = environment.localUserEmail;

  constructor(
    private authService: AuthService,
    private router: Router,
    public ngZone: NgZone,
    private _snackBar: MatSnackBar,
    @Inject(PLATFORM_ID) platformId: Object,
  ) {
    this.isBrowser = isPlatformBrowser(platformId);
  }

  ngOnInit(): void {
    if (!this.isBrowser) return;

    // Behind IAP the user is already authenticated; sync profile and enter app.
    if (!environment.isLocal) {
      this.continueSession();
    }
  }

  continueSession() {
    this.loader = true;
    this.authService.establishSession$().subscribe({
      next: () => {
        this.ngZone.run(() => {
          this.loader = false;
          void this.router.navigate([HOME_ROUTE]);
        });
      },
      error: error => {
        this.loader = false;
        handleErrorSnackbar(this._snackBar, error, 'Login Error');
      },
    });
  }
}
