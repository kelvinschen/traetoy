import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
const bot=fileURLToPath(new URL('../vendor/bloub/src/bot/',import.meta.url));
await build({stdin:{contents:`export {BotEngine} from './engine';export {EXPRESSIONS} from './expressions';export {SHAPES} from './skins';export {STATES} from './states';`,resolveDir:bot},bundle:true,platform:'node',format:'esm',outfile:fileURLToPath(new URL('.engine.mjs',import.meta.url))});
const {sequences,sequencePlayer}=await import('./sequences.mjs');
const signature=f=>JSON.stringify({body:f.bodyPath,eyes:f.eyes,alpha:f.bodyAlpha});
assert.equal(sequences.length,6);
let boundaries=0;
for(const s of sequences){
 const sample=sequencePlayer(s),points=new Set([0]);let at=0;
 for(const [,d] of s.steps){at+=d;points.add(Math.round(at*60));}
 assert.equal(at,s.reaction);
 for(let i=0;i<Math.round(s.duration*60);i++){
  const t=i/60,before=signature(sample.engine.sample(t)),f=sample(t);
  assert(f.bodyPath&&!JSON.stringify(f).includes('NaN'));
  if(s.name==='done' && t>=.5) assert(f.notif && f.notif.r>0,'notify marker must survive throughout its living tail');
  if(points.has(i)){
   assert.equal(signature(f),before,`${s.name}: pose must not jump at ${t}s`);
   boundaries++;
  }
 }
}
console.log(`PASS: six selected cloud schedules, ${boundaries} continuous boundaries and finite upstream poses`);
