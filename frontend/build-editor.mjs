import {build} from 'esbuild';
import {mkdir,writeFile,readFile,rm} from 'node:fs/promises';
// Next export copies new chunks; clear only its generated output first so
// previous deployment bundles are not shipped alongside the current build.
await rm('out',{recursive:true,force:true});
await rm('.next',{recursive:true,force:true});
await mkdir('public/editor',{recursive:true});
await build({stdin:{contents:"export * from './node_modules/monaco-editor/esm/vs/editor/editor.main.js'",resolveDir:process.cwd()},bundle:true,format:'esm',minify:true,outfile:'public/editor/monaco.js',loader:{'.ttf':'file'}});
for(const [name,entry] of Object.entries({editor:'editor/editor.worker.js',json:'language/json/json.worker.js',css:'language/css/css.worker.js',html:'language/html/html.worker.js',ts:'language/typescript/ts.worker.js'})){
 await build({entryPoints:[`node_modules/monaco-editor/esm/vs/${entry}`],bundle:true,format:'iife',minify:true,outfile:`public/editor/${name}.worker.js`});
}

for(const [name,path] of Object.entries({"MONACO-LICENSE.txt":"monaco-editor/LICENSE","MONACO-NOTICES.txt":"monaco-editor/ThirdPartyNotices.txt","XTERM-LICENSE.txt":"@xterm/xterm/LICENSE"}))await writeFile(`public/editor/${name}`,await readFile(`node_modules/${path}`));
await build({entryPoints:['lib/format-worker.mjs'],bundle:true,format:'iife',minify:true,outfile:'public/editor/format.worker.js'});
await writeFile('public/editor/PRETTIER-LICENSE.txt',await readFile('node_modules/prettier/LICENSE'));
