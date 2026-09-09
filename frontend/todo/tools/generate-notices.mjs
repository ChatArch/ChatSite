import fs from 'node:fs';
import path from 'node:path';

const root=path.resolve(import.meta.dirname,'..');
const lock=JSON.parse(fs.readFileSync(path.join(root,'package-lock.json'),'utf8'));
const sections=['ChatTodo frontend third-party notices','Generated from the exact production lockfile.',''];
for(const [key,meta] of Object.entries(lock.packages).sort(([a],[b])=>a.localeCompare(b))){
  if(!key||meta.dev)continue;
  const directory=path.join(root,key),manifestPath=path.join(directory,'package.json');
  if(!fs.existsSync(manifestPath))throw new Error(`Missing installed package: ${key}`);
  const manifest=JSON.parse(fs.readFileSync(manifestPath,'utf8'));
  const candidates=fs.readdirSync(directory).filter(name=>/^(licen[cs]e|copying|notice)(\..*)?$/i.test(name)).sort();
  sections.push(`${manifest.name || key.replace(/^node_modules\//,'')} ${manifest.version || meta.version}`);
  sections.push(`License: ${typeof manifest.license==='string'?manifest.license:'See package metadata'}`);
  for(const name of candidates){const file=path.join(directory,name);if(fs.statSync(file).isFile())sections.push('',`--- ${name} ---`,fs.readFileSync(file,'utf8').trim());}
  sections.push('','='.repeat(72),'');
}
fs.writeFileSync(path.join(root,'public','THIRD_PARTY_NOTICES.txt'),sections.join('\n').trim()+'\n');
