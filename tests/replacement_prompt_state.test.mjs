import assert from 'node:assert/strict';
import test from 'node:test';
import { videoPromptContent } from '../web/js/replacement_prompt_state.js';

const fixture = () => ({
  video: 'source.mp4', crop: null,
  compression: { width: 1080, height: 1920, max_edge: 0, crf: 18, fps: 24, resize_method: 'pad' },
  plan: { enabled: true, mode: 'MiniMax H3', frames: 124, seconds: 5.1667,
    overlap: 22, output: '完整片段', start: 0, end: 8 },
});

test('compression dimensions and H3 editor rounding preserve the described video content', () => {
  const before = fixture(), after = fixture();
  Object.assign(after.compression, { width: 540, height: 960, max_edge: 960, crf: 28 });
  after.plan.seconds = after.plan.frames / 24;
  after.crop = [0, 0, 1, 1];
  assert.equal(videoPromptContent(after), videoPromptContent(before));
});

test('changed segment boundaries, overlap, crop and media require another optimization', () => {
  for (const mutate of [
    config => { config.plan.start = 1 / 24; },
    config => { config.plan.end = 7; },
    config => { config.plan.frames = 141; },
    config => { config.plan.overlap = 5; },
    config => { config.crop = [0.1, 0, 0.9, 1]; },
    config => { config.video = 'other.mp4'; },
  ]) {
    const before = fixture(), after = fixture();
    mutate(after);
    assert.notEqual(videoPromptContent(after), videoPromptContent(before));
  }
});

test('editor filling the full source duration does not change the selected content', () => {
  const before = fixture(), after = fixture();
  before.plan.end = 0;
  after.plan.end = 8;
  assert.equal(videoPromptContent(before, 8), videoPromptContent(after, 8));
});
