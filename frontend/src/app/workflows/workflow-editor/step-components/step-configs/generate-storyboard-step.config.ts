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

const toOptions = (type: 'TEXT' | 'IMAGE') =>
  MODEL_CONFIGS.filter(model => model.type === type).map(model => ({
    value: model.value,
    label: model.viewValue,
  }));

/**
 * Storyboard step: free-text brief -> shot list (reasoning model) -> one
 * frame per shot (image model). Settings use their own names (not `model`)
 * because the step drives two models.
 */
export const GENERATE_STORYBOARD_STEP_CONFIG: StepConfig = {
  type: NodeTypes.GENERATE_STORYBOARD,
  title: 'Generate Storyboard',
  icon: 'view_comfy',
  inputs: [
    {
      name: 'brief',
      label: 'Video brief',
      type: 'textarea',
      required: true,
    },
    {
      name: 'reference_images',
      label: 'Product / reference images',
      type: 'image',
      required: false,
    },
  ],
  settings: [
    {
      name: 'reasoning_model',
      label: 'Planning model',
      type: 'select',
      options: toOptions('TEXT'),
      defaultValue: 'gemini-3-pro-preview',
    },
    {
      name: 'image_model',
      label: 'Frame model',
      type: 'select',
      options: toOptions('IMAGE'),
      defaultValue: 'gemini-3.1-flash-image-preview',
    },
    {
      name: 'aspect_ratio',
      label: 'Frame aspect ratio',
      type: 'select',
      options: [
        {value: '16:9', label: '16:9 Landscape'},
        {value: '9:16', label: '9:16 Vertical (Reels, Stories)'},
        {value: '1:1', label: '1:1 Square'},
        {value: '4:5', label: '4:5 Portrait feed'},
      ],
      defaultValue: '16:9',
    },
    {
      name: 'frame_style',
      label: 'Frame style',
      type: 'select',
      options: [
        {value: 'sketch', label: 'Pencil sketch'},
        {value: 'rough_color', label: 'Rough colour'},
        {value: 'photo_previz', label: 'Photo previz'},
      ],
      defaultValue: 'rough_color',
    },
    {
      name: 'max_frames',
      label: 'Max frames',
      type: 'slider',
      defaultValue: 8,
      min: 3,
      max: 12,
      step: 1,
    },
    {
      name: 'language',
      label: 'Board language',
      type: 'select',
      options: [
        {value: 'English', label: 'English'},
        {value: 'German', label: 'German'},
        {value: 'French', label: 'French'},
        {value: 'Spanish', label: 'Spanish'},
        {value: 'Italian', label: 'Italian'},
        {value: 'Romanian', label: 'Romanian'},
      ],
      defaultValue: 'English',
    },
    {
      name: 'brand_guidelines',
      label: 'Use Brand Guidelines',
      type: 'checkbox',
      defaultValue: true,
    },
    {
      name: 'brand_context',
      label: 'Brand context (optional, guides the planner)',
      type: 'textarea',
      defaultValue: '',
    },
  ],
  outputs: [
    {
      name: 'storyboard_frames',
      label: 'storyboard_frames',
      type: 'image',
    },
    {
      name: 'storyboard_text',
      label: 'storyboard_text',
      type: 'text',
    },
    {
      name: 'shot_list',
      label: 'shot_list',
      type: 'text',
    },
  ],
};
