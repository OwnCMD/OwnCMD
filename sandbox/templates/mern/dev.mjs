import {spawn} from 'node:child_process';import {mkdir,access} from 'node:fs/promises';import net from 'node:net';
const root=process.env.HOME||'/work';await mkdir(root+'/.data/mongo',{recursive:true});
const children=[];const start=(cmd,args)=>{const child=spawn(cmd,args,{stdio:'inherit'});children.push(child);child.on('error',e=>{console.error(e.message);process.exitCode=1;});return child;};
let existingData=false;try{await access(root+'/.data/mongo/WiredTiger');existingData=true;}catch{}
const mongo=start('mongod',['--dbpath',root+'/.data/mongo','--bind_ip','127.0.0.1','--port','27017','--wiredTigerCacheSizeGB','0.25']);
let ready=false;for(let i=0;i<100;i++){ready=await new Promise(r=>{const s=net.connect(27017,'127.0.0.1');s.on('connect',()=>{s.destroy();r(true);});s.on('error',()=>r(false));});if(ready)break;await new Promise(r=>setTimeout(r,100));}if(!ready)throw new Error('MongoDB did not start; inspect the service log and CPU support');
try{if(existingData)throw Object.assign(new Error('Database already exists'),{code:'ENOENT'});await access(root+'/.aster/mongodb.archive.gz');await new Promise((resolve,reject)=>{const p=spawn('mongorestore',['--host','127.0.0.1','--archive='+root+'/.aster/mongodb.archive.gz','--gzip','--drop'],{stdio:'inherit'});p.on('exit',c=>c?reject(new Error('Database restore failed')):resolve());});}catch(e){if(e.code!=='ENOENT')throw e;}
start('node',['server/index.mjs']);start('node',['node_modules/vite/bin/vite.js']);
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>{for(const child of children)child.kill('SIGTERM');});
