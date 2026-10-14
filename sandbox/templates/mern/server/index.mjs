import {MongoClient} from 'mongodb';import {createApp} from './app.mjs';
const client=new MongoClient('mongodb://127.0.0.1:27017');await client.connect();createApp(client.db('project')).listen(3001,'127.0.0.1',()=>console.log('API ready on port 3001'));
