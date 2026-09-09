import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'../../..','src/chatsite/todo_static');
const files=fs.readdirSync(root,{recursive:true}).map(String);
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
for(const match of html.matchAll(/(?:src|href)="([^"]+)"/g)){const url=match[1];if(!url.startsWith('./assets/'))throw new Error(`Non-relative asset: ${url}`);if(!fs.existsSync(path.join(root,url.slice('./assets/'.length))))throw new Error(`Missing asset: ${url}`);}
for(const forbidden of ['app.js','core.js','style.css'])if(files.includes(forbidden))throw new Error(`Obsolete asset retained: ${forbidden}`);
if(files.some(file=>file.endsWith('.map')))throw new Error('Source map found');
const publicText=files.filter(file=>/\.(?:js|css|html)$/i.test(file)).map(file=>fs.readFileSync(path.join(root,file),'utf8')).join('\n').toLowerCase();
for(const forbidden of ['assistant-ui','mind-elixir','candidate','/home/','wzhecnu.cn'])if(publicText.includes(forbidden))throw new Error(`Forbidden public token: ${forbidden}`);
for(const required of ['simple-mind-map','@ant-design/x','@ant-design/x-markdown'])if(!fs.readFileSync(path.join(root,'THIRD_PARTY_NOTICES.txt'),'utf8').includes(required))throw new Error(`Missing notice: ${required}`);
console.log(`verified ${files.length} production files`);
