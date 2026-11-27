import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import * as THREE from 'three';
import {animate} from 'animejs';
const here=path.dirname(fileURLToPath(import.meta.url));
const output=path.resolve(here,'../app/src/main/res/raw');
fs.mkdirSync(output,{recursive:true});
const round=x=>Number(x.toFixed(6));
const camera=new THREE.OrthographicCamera(-1.85,1.85,1.39,-1.39,.1,30);
camera.position.set(0,0,8);camera.lookAt(0,0,0);camera.updateProjectionMatrix();
const geometry=new THREE.EdgesGeometry(new THREE.BoxGeometry(1.65,.34,.8));
const vertices=geometry.getAttribute('position');
const frames=[];
for(let frame=0;frame<=48;frame++){
 const phase=frame/48*Math.PI*2;
 const lines=[];
 const project=(p,matrix)=>{const v=p.clone().applyMatrix4(matrix).project(camera);return [round((v.x+1)/2),round((1-v.y)/2)];};
 for(let tier=0;tier<3;tier++){
  const group=new THREE.Object3D();group.rotation.set(.24+Math.sin(phase)*.035,-.42+Math.sin(phase)*.10,.02);
  group.position.y=(tier-1)*.58;group.updateMatrixWorld(true);
  for(let i=0;i<vertices.count;i+=2){
   const a=project(new THREE.Vector3().fromBufferAttribute(vertices,i),group.matrixWorld);
   const b=project(new THREE.Vector3().fromBufferAttribute(vertices,i+1),group.matrixWorld);
   lines.push([...a,...b]);
  }
  for(let slot=0;slot<3;slot++){
   const a=project(new THREE.Vector3(-.55+slot*.32,0,.405),group.matrixWorld);
   const b=project(new THREE.Vector3(-.37+slot*.32,0,.405),group.matrixWorld);
   lines.push([...a,...b]);
  }
 }
 frames.push(lines);
}
const target={progress:0};
const timeline=animate(target,{progress:1,duration:1000,ease:'outCubic',autoplay:false});
const ease=[];for(let i=0;i<=100;i++){timeline.seek(i*10,true);ease.push(round(target.progress));}timeline.pause();
fs.writeFileSync(path.join(output,'motion_scene.json'),JSON.stringify({schema:1,geometryProducer:'three@0.187.0',easingProducer:'animejs@4.5.0',frames,ease}));
console.log(`Generated ${frames.length} server frames and ${ease.length} Anime.js easing samples.`);
