// Product-selected fixed cloud sequences, in seconds. The upstream engine stays unchanged.
import {BotEngine, SHAPES, EXPRESSIONS} from './.engine.mjs';
export const sequences = [
 {name:'idle',loop:true,steps:[['blase',5],['swirl',4],['play',4],['somnolent',5]]},
 {name:'work',loop:true,steps:[['attentif',6],['thinking',3],['wide',6],['thinking',3],['curieux',6]]},
 {name:'done',steps:[['notify',2.2]],tail:4},
 {name:'ack',steps:[['wink',3],['excite',3]]},
 {name:'stop',steps:[['surpris',2.5],['alert',3]],tail:4},
 {name:'offline',loop:true,steps:[['effraye',2.4],['exclaim',4]]}
].map(s=>({...s,reaction:s.steps.reduce((n,v)=>n+v[1],0),duration:s.steps.reduce((n,v)=>n+v[1],0)+(s.loop?.45:s.tail||0)}));
export function sequencePlayer(s) {
 const ex=id=>EXPRESSIONS.find(e=>e.id===id);
 const engine=new BotEngine(100,'idle',SHAPES.find(v=>v.id==='nuage').radii,ex(s.steps[0][0])||ex('neutre'));
 let next=0,at=0;
 const apply=(id,time)=>{
   // A direct action-to-action change preserves the engine's outgoing eye
   // offset. An intermediate idle at the same timestamp loses that origin.
   if(ex(id)){engine.setState('idle',time);engine.setExpression(ex(id),time);}
   else engine.setState(id,time);
 };
 const sample=t=>{
   while(next<s.steps.length && t>=at-1e-7){const [id,d]=s.steps[next++];apply(id,at);at+=d;}
   if(s.loop&&next===s.steps.length&&t>=at-1e-7){apply(s.steps[0][0],at);next++;}
   return engine.sample(t);
 };
 sample.engine=engine; // Expose the actual engine for boundary continuity checks.
 return sample;
}
