import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';
import { NetworkStack } from './network-stack';

interface DataStackProps extends cdk.StackProps {
  network: NetworkStack;
}

export class DataStack extends cdk.Stack {
  readonly db: rds.DatabaseInstance;
  readonly dbSecret: rds.DatabaseSecret;
  readonly fastForwardTable: dynamodb.Table;
  readonly submissionQueue: sqs.Queue;
  readonly readDbSecretPolicy: iam.ManagedPolicy;
  readonly readFastForwardTablePolicy: iam.ManagedPolicy;
  readonly sendToSubmissionQueuePolicy: iam.ManagedPolicy;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);

    // ── RDS ──────────────────────────────────────────────────────────────────

    this.dbSecret = new rds.DatabaseSecret(this, 'DbSecret', {
      username: 'claimsadmin',
      secretName: 'claims/database-credentials',
    });

    this.db = new rds.DatabaseInstance(this, 'Db', {
      instanceIdentifier: 'claims-db',
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_15,
      }),
      instanceType: ec2.InstanceType.of(
        ec2.InstanceClass.T3,
        ec2.InstanceSize.MICRO,
      ),
      credentials: rds.Credentials.fromSecret(this.dbSecret),
      databaseName: 'claims',
      vpc: props.network.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroups: [props.network.rdsSg],
      multiAz: false,
      allocatedStorage: 20,
      backupRetention: cdk.Duration.days(7),
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
      publiclyAccessible: false,
    });

    // ── RDS auto stop/start ───────────────────────────────────────────────────
    // 10pm PDT = 05:00 UTC (stop), 4pm PDT = 23:00 UTC (start).

    const schedulerRole = new iam.Role(this, 'RdsSchedulerRole', {
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
      inlinePolicies: {
        RdsStartStop: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: ['rds:StopDBInstance', 'rds:StartDBInstance'],
              resources: [this.db.instanceArn],
            }),
          ],
        }),
      },
    });

    new scheduler.CfnSchedule(this, 'RdsStopSchedule', {
      name: 'claims-rds-stop',
      scheduleExpression: 'cron(0 5 * * ? *)',   // 10pm PDT
      flexibleTimeWindow: { mode: 'OFF' },
      target: {
        arn: 'arn:aws:scheduler:::aws-sdk:rds:stopDBInstance',
        roleArn: schedulerRole.roleArn,
        input: JSON.stringify({ DbInstanceIdentifier: 'claims-db' }),
      },
    });

    new scheduler.CfnSchedule(this, 'RdsStartSchedule', {
      name: 'claims-rds-start',
      scheduleExpression: 'cron(0 23 * * ? *)',  // 4pm PDT
      flexibleTimeWindow: { mode: 'OFF' },
      target: {
        arn: 'arn:aws:scheduler:::aws-sdk:rds:startDBInstance',
        roleArn: schedulerRole.roleArn,
        input: JSON.stringify({ DbInstanceIdentifier: 'claims-db' }),
      },
    });

    // ── DynamoDB ──────────────────────────────────────────────────────────────

    this.fastForwardTable = new dynamodb.Table(this, 'FastForwardTable', {
      tableName: 'claims-fast-forward',
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── SQS ───────────────────────────────────────────────────────────────────
    // Lives in DataStack so ApiStack can receive the URL on first deploy
    // without depending on WorkersStack.

    const dlq = new sqs.Queue(this, 'SubmissionDlq', {
      queueName: 'claims-submission-dlq',
      retentionPeriod: cdk.Duration.days(14),
    });

    this.submissionQueue = new sqs.Queue(this, 'SubmissionQueue', {
      queueName: 'claims-submission',
      visibilityTimeout: cdk.Duration.seconds(30),
      deadLetterQueue: { queue: dlq, maxReceiveCount: 3 },
    });

    // ── IAM managed policies (shared across stacks) ───────────────────────────

    this.readDbSecretPolicy = new iam.ManagedPolicy(this, 'ReadDbSecretPolicy', {
      managedPolicyName: 'ClaimsReadDbSecret',
      statements: [
        new iam.PolicyStatement({
          actions: ['secretsmanager:GetSecretValue'],
          resources: [this.dbSecret.secretArn],
        }),
      ],
    });

    this.readFastForwardTablePolicy = new iam.ManagedPolicy(this, 'ReadFastForwardTablePolicy', {
      managedPolicyName: 'ClaimsFastForwardDynamoDB',
      statements: [
        new iam.PolicyStatement({
          actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem'],
          resources: [this.fastForwardTable.tableArn],
        }),
      ],
    });

    this.sendToSubmissionQueuePolicy = new iam.ManagedPolicy(this, 'SendToSubmissionQueuePolicy', {
      managedPolicyName: 'ClaimsSendToSubmissionQueue',
      statements: [
        new iam.PolicyStatement({
          actions: ['sqs:SendMessage'],
          resources: [this.submissionQueue.queueArn],
        }),
      ],
    });
  }
}
