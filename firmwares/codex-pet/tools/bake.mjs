// Compile the unmodified upstream engine; rasterize its exact SVG at 60 Hz.
import {build} from 'esbuild';
import {Resvg} from '@resvg/resvg-js';
import {deflateRawSync} from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
await build({stdin:{contents:`export {BotEngine} from './engine';export {EXPRESSIONS} from './expressions';export {SHAPES} from './skins';export {STATES,SEQUENCE} from './states';`,resolveDir:root+'/vendor/bloub/src/bot'},bundle:true,platform:'node',format:'esm',outfile:root+'/tools/.engine.mjs'});
const {EXPRESSIONS,SHAPES,STATES,SEQUENCE}=await import('./.engine.mjs');
const {sequences,sequencePlayer}=await import('./sequences.mjs');
const W=192,FPS=60,PAPER='#f9f9f9',INK='#0a0a0c';
const gray=c=>{const v=[1,3,5].map(i=>parseInt(c.slice(i,i+2),16));let n=Math.round(v[0]*.2126+v[1]*.7152+v[2]*.0722);return `rgb(${n},${n},${n})`;};
function svg(f){
 const arc=(a,side)=>`<path d="${a[side]}" stroke="url(#${a.id})" stroke-width="${a.width}" opacity="${a.opacity}"/>`;
 const dot=d=>{let fill=d.color?gray(d.color):d.depth===undefined?INK:gray('#'+[0,1,2].map(i=>Math.round(249+(i===2?12:10)-249).toString(16).padStart(2,'0')).join(''));if(d.depth!==undefined)fill=`rgb(${249-239*d.depth},${249-239*d.depth},${249-237*d.depth})`;return d.d?`<path d="${d.d}" transform="translate(${d.x} ${d.y}) rotate(${d.rot||0}) scale(100)" fill="${fill}" opacity="${d.opacity}"/>`:`<circle cx="${d.x}" cy="${d.y}" r="${d.r}" fill="${fill}" opacity="${d.opacity}"/>`;};
 const dots=f.dots.map(dot).join('');
 return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${W}" viewBox="-158 -158 316 316"><rect x="-158" y="-158" width="316" height="316" fill="${PAPER}"/><defs><mask id="body" maskUnits="userSpaceOnUse" x="-158" y="-158" width="316" height="316"><path d="${f.bodyPath}" fill="white"/>${f.eyes.map(e=>`<path d="${e.d}" transform="${e.matrix}" opacity="${e.alpha}" fill="black"/>`).join('')}${f.notch?`<circle cx="${f.notch.x}" cy="${f.notch.y}" r="${f.notch.r}" fill="black"/>`:''}</mask>${f.arcs.map(a=>`<linearGradient id="${a.id}" gradientUnits="userSpaceOnUse" x1="${a.grad.x1}" y1="${a.grad.y1}" x2="${a.grad.x2}" y2="${a.grad.y2}">${a.grad.stops.map((c,i)=>`<stop offset="${i/(a.grad.stops.length-1)}" stop-color="${gray(c)}"/>`).join('')}</linearGradient>`).join('')}</defs><g fill="none" stroke-linecap="round">${f.arcs.map(a=>arc(a,'back')).join('')}</g>${f.dotsBehind?dots:''}<g opacity="${f.bodyAlpha}"><path d="${f.bodyPath}" fill="${PAPER}"/><g mask="url(#body)"><rect x="-158" y="-158" width="316" height="316" fill="${INK}"/></g></g>${!f.dotsBehind?dots:''}${f.notif?`<circle cx="${f.notif.x}" cy="${f.notif.y}" r="${f.notif.r}" fill="#f4782a"/>`:''}<g fill="none" stroke-linecap="round">${f.arcs.map(a=>arc(a,'front')).join('')}</g></svg>`;
}
const clips=sequences;
const blobs=[],rows=[],previews=[],payloads=new Map();let offset=0;
fs.mkdirSync(root+'/assets',{recursive:true});fs.mkdirSync(root+'/build/previews',{recursive:true});
for(const clip of clips){
 const sample=sequencePlayer(clip);let first=null,tailFirst=null;let prev=Buffer.alloc(W*W/2,0xee),records=[],count=Math.round(clip.duration*FPS),returned=false;
 for(let i=0;i<count;i++){
  const t=i/FPS;
  const source=svg(sample(t));const raster=new Resvg(source,{font:{loadSystemFonts:false}}).render();const rgba=raster.pixels;
  const packed=Buffer.alloc(W*W/2);for(let p=0;p<W*W;p++){const r=rgba[p*4],g=rgba[p*4+1],b=rgba[p*4+2];const v=r>g+30&&g>b+20?15:Math.max(0,Math.min(14,Math.round(((r+g+b)/3-10)*14/239)));packed[p>>1]|=v<<((p&1)?0:4);}
  if(i===0)first=Buffer.from(packed);
  if(i===Math.round(clip.reaction*FPS))tailFirst=Buffer.from(packed);
  // Close breathing/gaze phase at the loop seam without resetting to neutral.
  const seam=clip.loop?first:clip.tail?tailFirst:null;
  if(seam && i>=count-9){const mix=(i-(count-9)+1)/9;for(let j=0;j<packed.length;j++){let v=0;for(const shift of [0,4]){const a=(packed[j]>>shift)&15,b=(seam[j]>>shift)&15;v|=(a===15||b===15?(mix<.5?a:b):Math.round(a+(b-a)*mix))<<shift;}packed[j]=v;}}
  const key=i%60===0 || i===Math.round(clip.reaction*FPS),delta=Buffer.alloc(packed.length);for(let j=0;j<delta.length;j++)delta[j]=packed[j]^(key?0:prev[j]);
  const encoded=deflateRawSync(delta,{level:9}), fingerprint=encoded.toString('base64');
  let payloadOffset=payloads.get(fingerprint);
  if(payloadOffset===undefined){payloadOffset=offset;payloads.set(fingerprint,offset);blobs.push(encoded);offset+=encoded.length;}
  records.push({offset:payloadOffset,size:encoded.length,key});prev=packed;
  if(i===Math.min(count-45,72)){fs.writeFileSync(root+`/build/previews/${clip.name}.png`,raster.asPng());fs.writeFileSync(root+`/build/previews/${clip.name}.svg`,source);previews.push({name:clip.name,svg:source});}
 }
 rows.push({...clip,expression:undefined,shape:undefined,frames:records});console.log(`${clip.name}: ${count} frames, total ${(offset/1024).toFixed(0)} KiB`);
}
fs.writeFileSync(root+'/assets/bloub.bin',Buffer.concat(blobs));
fs.writeFileSync(root+'/assets/bloub.json',JSON.stringify({upstream:'b4bb3c1b5f93c7b87a2e8d620f667c4093d97749',fps:FPS,width:W,clips:rows},null,2)+'\n');
let all=[],starts=[];for(const r of rows){starts.push(all.length);all.push(...r.frames);}
let h=`/* Generated by tools/bake.mjs from pinned Bloub source. */\n#pragma once\n#define PET_W ${W}\n#define PET_FPS ${FPS}\n#define PET_CLIP_COUNT ${rows.length}\ntypedef struct { unsigned offset; unsigned short size; unsigned char key; } pet_frame_record_t;\ntypedef struct { const char *name; unsigned short start,count,loop_start,reaction; } pet_clip_t;\nextern const pet_frame_record_t pet_frames[${all.length}];\nextern const pet_clip_t pet_clips[PET_CLIP_COUNT];\n`;
fs.writeFileSync(root+'/main/pet_assets.h',h);
fs.writeFileSync(root+'/main/pet_assets.c',`#include "pet_assets.h"\nconst pet_frame_record_t pet_frames[]={\n${all.map(r=>`{${r.offset},${r.size},${+r.key}}`).join(',\n')}\n};\nconst pet_clip_t pet_clips[]={\n${rows.map((r,i)=>`{"${r.name}",${starts[i]},${r.frames.length},${r.loop?0:r.tail?Math.round(r.reaction*FPS):r.frames.length-1},${Math.round(r.reaction*FPS)}}`).join(',\n')}\n};\n`);
fs.writeFileSync(root+'/build/previews/index.html',`<!doctype html><meta charset="utf-8"><title>Bloub firmware source frames</title><style>body{background:#eee;font:14px sans-serif}main{display:grid;grid-template-columns:repeat(8,192px);gap:12px}figure{margin:0}img{width:192px}</style><h1>Actual upstream engine frames · 192 px / 60 Hz</h1><main>${previews.map(p=>`<figure><img src="${p.name}.png"><figcaption>${p.name}</figcaption></figure>`).join('')}</main>`);
console.log(`Assets: ${offset} bytes, ${all.length} frames, ${rows.length} clips`);
