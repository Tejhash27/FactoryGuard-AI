import {spawn} from 'node:child_process';
const backend=spawn('python',['-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000'],{stdio:'inherit'});
const frontend=spawn(process.execPath,['node_modules/vite/bin/vite.js','frontend','--host','0.0.0.0','--port','3000'],{stdio:'inherit'});
const stop=()=>{frontend.kill();backend.kill();};
process.on('SIGTERM',stop);process.on('SIGINT',stop);
frontend.on('exit',code=>{backend.kill();process.exit(code||0);});
backend.on('error',e=>console.error('Backend unavailable:',e.message));
