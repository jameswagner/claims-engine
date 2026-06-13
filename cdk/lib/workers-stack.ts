import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as lambda_event_sources from 'aws-cdk-lib/aws-lambda-event-sources';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import * as path from 'path';
import { DataStack } from './data-stack';
import { NetworkStack } from './network-stack';

interface WorkersStackProps extends cdk.StackProps {
  network: NetworkStack;
  data: DataStack;
}

export class WorkersStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: WorkersStackProps) {
    super(scope, id, props);

    const commonVpcConfig = {
      vpc: props.network.vpc,
      allowPublicSubnet: true,
      securityGroups: [props.network.lambdaSg],
    };

    const commonEnv = {
      DB_SECRET_ARN: props.data.dbSecret.secretArn,
    };

    // ── Submission worker ─────────────────────────────────────────────────────

    const submissionWorker = new lambda.DockerImageFunction(this, 'SubmissionWorker', {
      functionName: 'claims-submission-worker',
      code: lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, '../../backend'),
        {
          file: 'Dockerfile.lambda',
          platform: cdk.aws_ecr_assets.Platform.LINUX_AMD64,
          cmd: ['app.handlers.submission_handler.handler'],
        },
      ),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment: commonEnv,
      ...commonVpcConfig,
    });

    submissionWorker.role!.addManagedPolicy(props.data.readDbSecretPolicy);

    submissionWorker.addEventSource(
      new lambda_event_sources.SqsEventSource(props.data.submissionQueue, {
        batchSize: 1,
      }),
    );

    // ── Remittance worker ─────────────────────────────────────────────────────

    const remittanceWorker = new lambda.DockerImageFunction(this, 'RemittanceWorker', {
      functionName: 'claims-remittance-worker',
      code: lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, '../../backend'),
        {
          file: 'Dockerfile.lambda',
          platform: cdk.aws_ecr_assets.Platform.LINUX_AMD64,
          cmd: ['app.handlers.remittance_handler.handler'],
        },
      ),
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      environment: commonEnv,
      ...commonVpcConfig,
    });

    remittanceWorker.role!.addManagedPolicy(props.data.readDbSecretPolicy);

    const schedulerRole = new iam.Role(this, 'RemittanceSchedulerRole', {
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
      inlinePolicies: {
        InvokeLambda: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: ['lambda:InvokeFunction'],
              resources: [remittanceWorker.functionArn],
            }),
          ],
        }),
      },
    });

    new scheduler.CfnSchedule(this, 'RemittanceSchedule', {
      name: 'claims-remittance-every-minute',
      scheduleExpression: 'rate(1 minute)',
      flexibleTimeWindow: { mode: 'OFF' },
      target: {
        arn: remittanceWorker.functionArn,
        roleArn: schedulerRole.roleArn,
      },
    });
  }
}
