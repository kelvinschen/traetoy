import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
const bot = fileURLToPath(new URL('../vendor/bloub/src/bot/', import.meta.url));
await build({stdin:{contents:`export {BotEngine} from './engine';export {EXPRESSIONS} from './expressions';export {SHAPES} from './skins';export {STATES,SEQUENCE} from './states';`,resolveDir:bot},bundle:true,platform:'node',format:'esm',outfile:fileURLToPath(new URL('.engine.mjs',import.meta.url))});
const {BotEngine,SHAPES,EXPRESSIONS}=await import('./.engine.mjs');
const {beginClip,advanceClip}=await import('./clip_timeline.mjs');
const signature = frame => JSON.stringify({eyes:frame.eyes, body:frame.bodyPath});
let failures=[];
for (const expression of EXPRESSIONS) {
  const clip={expression,duration:expression.id==='neutre'?6:4};
  const engine=beginClip();let returned=false;
  const neutral=EXPRESSIONS.find(e=>e.id==='neutre');
  const from=new BotEngine(100,'idle',SHAPES[0].radii,neutral);
  const target=new BotEngine(100,'idle',SHAPES[0].radii,expression);
  const exitFrame=Math.ceil((clip.duration-.65)*60);
  for (let i=0;i<clip.duration*60;i++) {
    const t=i/60, boundary=i===12||(!returned&&t>=clip.duration-.65);
    const before=boundary?signature(engine.sample(t)):null;
    returned=advanceClip(engine,clip,i,60,returned);
    if (boundary && before!==signature(engine.sample(t)))
      failures.push(`${expression.id} ${i===12?'enter':'exit'}: geometry jumped at t=${t}`);
    if (expression!==neutral && (i===21 || i===exitFrame+9)) {
      const mid=signature(engine.sample(t));
      assert.notEqual(mid,signature(from.sample(t)), `${expression.id}: intermediate pose must move away from neutral`);
      assert.notEqual(mid,signature(target.sample(t)), `${expression.id}: intermediate pose must not jump to target`);
    }
    if (i===39) assert.equal(signature(engine.sample(t)),signature(target.sample(t)));
    if (i===exitFrame+28) assert.equal(signature(engine.sample(t)),signature(from.sample(t)));
  }
}
assert.equal(failures.length,0,'Expression boundary must start from the current pose:\n'+failures.join('\n'));
console.log('PASS: all 16 expressions enter and exit continuously at the real baking call site');
