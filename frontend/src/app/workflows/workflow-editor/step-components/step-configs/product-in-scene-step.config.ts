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

const IMAGE_MODELS = [
  'gemini-3-pro-image-preview',
  'gemini-3.1-flash-image-preview',
  'gemini-3.1-flash-lite-image',
];

const model_options = MODEL_CONFIGS.filter(model =>
  IMAGE_MODELS.includes(model.value),
).map(model => ({value: model.value, label: model.viewValue}));

/**
 * Product in Scene: places an Own Brand packshot into a generated scene,
 * then checks with Gemini that the packaging text is unchanged. Failed
 * checks are retried and, if still failing, flagged for human review.
 */
export const PRODUCT_IN_SCENE_STEP_CONFIG: StepConfig = {
  type: NodeTypes.PRODUCT_IN_SCENE,
  title: 'Product in Scene',
  icon: 'storefront',
  inputs: [
    {
      name: 'product_image',
      label: 'Product Packshot',
      type: 'image',
      required: true,
    },
    {
      name: 'scene_prompt',
      label: 'Scene Description',
      type: 'textarea',
      required: true,
    },
  ],
  settings: [
    {
      name: 'model',
      label: 'Model',
      type: 'select',
      options: model_options,
      defaultValue: 'gemini-3-pro-image-preview',
    },
    {
      name: 'aspect_ratio',
      label: 'Aspect Ratio',
      type: 'select',
      options: [],
      defaultValue: '1:1',
    },
    {
      name: 'max_attempts',
      label: 'Attempts before human review',
      type: 'slider',
      defaultValue: 2,
      min: 1,
      max: 3,
      step: 1,
    },
    {
      name: 'brand_guidelines',
      label: 'Use Brand Guidelines',
      type: 'checkbox',
      defaultValue: false,
    },
  ],
  outputs: [
    {name: 'generated_image', label: 'generated_image', type: 'image'},
    {name: 'fidelity_passed', label: 'fidelity_passed', type: 'text'},
    {name: 'needs_review', label: 'needs_review', type: 'text'},
    {name: 'fidelity_report', label: 'fidelity_report', type: 'text'},
  ],
};
