#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { NetworkStack } from '../lib/network-stack';
import { DataStack } from '../lib/data-stack';
import { ApiStack } from '../lib/api-stack';
import { WorkersStack } from '../lib/workers-stack';
import { FrontendStack } from '../lib/frontend-stack';

const app = new cdk.App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: 'us-west-1' };

const network = new NetworkStack(app, 'claims-network', { env });
const data = new DataStack(app, 'claims-data', { env, network });
new ApiStack(app, 'claims-api', { env, network, data });
new WorkersStack(app, 'claims-workers', { env, network, data });
new FrontendStack(app, 'claims-frontend', { env });
