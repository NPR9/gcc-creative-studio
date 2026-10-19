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

import {MODEL_CONFIGS} from '../../../../common/config/model-config';
import {NodeTypes} from '../../../workflow.models';
import {StepConfig} from '../generic-step/step.model';

const final_model_options = MODEL_CONFIGS.filter(
  model =>
    model.value === 'gemini-3.1-flash-image-preview' ||
    model.value === 'gemini-3-pro-image-preview',
).map(model => ({value: model.value, label: model.viewValue}));

/**
 * Asset Multiplication: one master visual becomes every size in a channel
 * preset. Each native aspect ratio is rendered once (preview with Nano
 * Banana 2 Lite, final with the chosen model), then cropped to exact pixels
 * with headline, CTA and logo set as real text, never painted by the model.
 * Sizes and presets come from the backend size library.
 */
export const ASSET_MULTIPLICATION_STEP_CONFIG: StepConfig = {
  type: NodeTypes.ASSET_MULTIPLICATION,
  title: 'Asset Multiplication',
  icon: 'dashboard_customize',
  inputs: [
    {
      name: 'master_image',
      label: 'Master Visual',
      type: 'image',
      required: true,
    },
    {name: 'headline', label: 'Headline', type: 'textarea', required: false},
    {name: 'cta_text', label: 'CTA Button Text', type: 'text', required: false},
    {name: 'logo_image', label: 'Logo', type: 'image', required: false},
  ],
  settings: [
    {
      name: 'channel_preset',
      label: 'Channel',
      type: 'select',
      options: [
        {value: 'meta', label: 'Meta'},
        {value: 'demandgen', label: 'DemandGen (online purchase)'},
        {value: 'pmax', label: 'Performance Max'},
      ],
      defaultValue: 'meta',
    },
    {
      name: 'sizes',
      label: 'Sizes (optional, comma-separated ids)',
      type: 'text',
      defaultValue: '',
    },
    {
      name: 'quality',
      label: 'Quality',
      type: 'radio',
      options: [
        {value: 'preview', label: 'Preview (1K)'},
        {value: 'final', label: 'Final render'},
      ],
      defaultValue: 'preview',
    },
    {
      name: 'final_model',
      label: 'Final Render Model',
      type: 'select',
      options: final_model_options,
      defaultValue: 'gemini-3.1-flash-image-preview',
    },
    {
      name: 'cta',
      label: 'CTA Button',
      type: 'select',
      options: [
        {value: 'auto', label: 'Follow channel rule'},
        {value: 'on', label: 'Always'},
        {value: 'off', label: 'Never'},
      ],
      defaultValue: 'auto',
    },
    {
      name: 'brand_guidelines',
      label: 'Use Brand Guidelines',
      type: 'checkbox',
      defaultValue: false,
    },
  ],
  outputs: [
    {name: 'images', label: 'images', type: 'image'},
    {name: 'manifest', label: 'manifest', type: 'text'},
  ],
};
