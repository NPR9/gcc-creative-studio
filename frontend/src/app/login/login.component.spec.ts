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

import {ComponentFixture, TestBed, fakeAsync, tick} from '@angular/core/testing';
import {LoginComponent} from './login.component';
import {Router} from '@angular/router';
import {AuthService} from './../common/services/auth.service';
import {MatSnackBar} from '@angular/material/snack-bar';
import {NoopAnimationsModule} from '@angular/platform-browser/animations';
import {of, throwError} from 'rxjs';
import {NgZone, PLATFORM_ID} from '@angular/core';

class MockAuthService {
  establishSession$ = jasmine.createSpy('establishSession$');
}

describe('LoginComponent', () => {
  let component: LoginComponent;
  let fixture: ComponentFixture<LoginComponent>;
  let authService: MockAuthService;
  let router: jasmine.SpyObj<Router>;
  let snackBar: jasmine.SpyObj<MatSnackBar>;

  beforeEach(async () => {
    const routerSpy = jasmine.createSpyObj('Router', ['navigate']);
    const snackBarSpy = jasmine.createSpyObj('MatSnackBar', ['open']);

    await TestBed.configureTestingModule({
      declarations: [LoginComponent],
      imports: [NoopAnimationsModule],
      providers: [
        {provide: AuthService, useClass: MockAuthService},
        {provide: Router, useValue: routerSpy},
        {provide: MatSnackBar, useValue: snackBarSpy},
        {provide: PLATFORM_ID, useValue: 'browser'},
        {
          provide: NgZone,
          useFactory: () => new NgZone({enableLongStackTrace: false}),
        },
      ],
    })
      .overrideTemplate(LoginComponent, '<button (click)="continueSession()">Continue</button>')
      .compileComponents();

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    authService = TestBed.inject(AuthService) as unknown as MockAuthService;
    router = TestBed.inject(Router) as jasmine.SpyObj<Router>;
    snackBar = TestBed.inject(MatSnackBar) as jasmine.SpyObj<MatSnackBar>;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should establish session and navigate home on continue', fakeAsync(() => {
    authService.establishSession$.and.returnValue(
      of({email: 'dev@example.com'} as any),
    );
    component.continueSession();
    tick();
    expect(authService.establishSession$).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/']);
    expect(component.loader).toBeFalse();
  }));

  it('should show snackbar on session failure', fakeAsync(() => {
    authService.establishSession$.and.returnValue(
      throwError(() => new Error('fail')),
    );
    component.continueSession();
    tick();
    expect(component.loader).toBeFalse();
    expect(snackBar.open).toHaveBeenCalled();
  }));
});
