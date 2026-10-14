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

import {Component, OnInit} from '@angular/core';
import {MatDialogRef} from '@angular/material/dialog';
import {
  AdminDashboardService,
  UnitPriceRow,
} from '../../services/admin/admin-dashboard.service';

@Component({
  selector: 'app-unit-prices-dialog',
  templateUrl: './unit-prices-dialog.component.html',
  styleUrls: ['./unit-prices-dialog.component.scss'],
})
export class UnitPricesDialogComponent implements OnInit {
  isLoading = true;
  errorMessage: string | null = null;
  prices: UnitPriceRow[] = [];
  columns = ['model', 'unitType', 'price', 'notes'];

  constructor(
    private dialogRef: MatDialogRef<UnitPricesDialogComponent>,
    private adminDashboardService: AdminDashboardService,
  ) {}

  ngOnInit(): void {
    this.adminDashboardService.getUnitPrices().subscribe({
      next: prices => {
        this.prices = (prices || []).sort((a, b) =>
          a.model.localeCompare(b.model),
        );
        this.isLoading = false;
      },
      error: err => {
        this.errorMessage =
          err?.error?.detail ||
          err?.message ||
          'Failed to load unit prices.';
        this.isLoading = false;
      },
    });
  }

  close(): void {
    this.dialogRef.close();
  }

  unitTypeLabel(unitType: string): string {
    switch (unitType) {
      case 'input_token':
        return 'Input token';
      case 'output_token':
        return 'Output token';
      case 'image':
        return 'Image';
      case 'video_second':
        return 'Video second';
      case 'audio_clip':
        return 'Audio clip';
      default:
        return unitType;
    }
  }

  formatPrice(row: UnitPriceRow): string {
    const value = Number(row.unitPriceUsd);
    if (row.unitType === 'input_token' || row.unitType === 'output_token') {
      return `$${(value * 1_000_000).toFixed(2)} / 1M tokens`;
    }
    if (row.unitType === 'image') {
      return `$${value.toFixed(4)} / image`;
    }
    if (row.unitType === 'video_second') {
      return `$${value.toFixed(2)} / second`;
    }
    if (row.unitType === 'audio_clip') {
      return `$${value.toFixed(4)} / clip`;
    }
    return `$${value}`;
  }
}
