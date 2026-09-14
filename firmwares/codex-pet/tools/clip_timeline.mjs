// Shared by baking and the continuity regression: these calls are the adapter
// between firmware clips and the unmodified upstream animation engine.
import {BotEngine, SHAPES, EXPRESSIONS} from './.engine.mjs';
const neutral = EXPRESSIONS.find(expression => expression.id === 'neutre');
export function beginClip() {
  return new BotEngine(100, 'idle', SHAPES[0].radii, neutral);
}
export function advanceClip(engine, clip, frame, fps, returned) {
  const t = frame / fps;
  if (frame === 12) {
    if (clip.expression) engine.setExpression(clip.expression, t);
    if (clip.state) engine.setState(clip.state, t);
    if (clip.shape) engine.setShape(clip.shape, t);
  }
  if (!returned && t >= clip.duration - .65) {
    engine.setState('idle', t);
    engine.setExpression(neutral, t);
    engine.setShape(SHAPES[0].radii, t);
    return true;
  }
  return returned;
}
