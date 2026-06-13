import * as cdk from 'aws-cdk-lib';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import * as path from 'path';
import { DataStack } from './data-stack';
import { NetworkStack } from './network-stack';

interface ApiStackProps extends cdk.StackProps {
  network: NetworkStack;
  data: DataStack;
}

export class ApiStack extends cdk.Stack {
  readonly apiUrl: string;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const fn = new lambda.DockerImageFunction(this, 'ApiFunction', {
      functionName: 'claims-api',
      code: lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, '../../backend'),
        { file: 'Dockerfile.lambda', platform: cdk.aws_ecr_assets.Platform.LINUX_AMD64 },
      ),
      timeout: cdk.Duration.seconds(300),
      memorySize: 512,
      vpc: props.network.vpc,
      allowPublicSubnet: true,
      securityGroups: [props.network.lambdaSg],
      environment: {
        DB_SECRET_ARN: props.data.dbSecret.secretArn,
        SUBMISSION_QUEUE_URL: props.data.submissionQueue.queueUrl,
        FAST_FORWARD_TABLE: props.data.fastForwardTable.tableName,
        ALLOWED_ORIGINS: '*',
      },
    });

    fn.role!.addManagedPolicy(props.data.readDbSecretPolicy);
    fn.role!.addManagedPolicy(props.data.readFastForwardTablePolicy);
    fn.role!.addManagedPolicy(props.data.sendToSubmissionQueuePolicy);

    const httpApi = new apigwv2.HttpApi(this, 'HttpApi', {
      apiName: 'claims-api',
      corsPreflight: {
        allowOrigins: ['*'],
        allowMethods: [apigwv2.CorsHttpMethod.ANY],
        allowHeaders: ['Content-Type', 'Authorization', 'X-Request-ID', 'Idempotency-Key'],
        exposeHeaders: ['X-Request-ID'],
        maxAge: cdk.Duration.minutes(5),
      },
    });

    httpApi.addRoutes({
      path: '/{proxy+}',
      methods: [apigwv2.HttpMethod.ANY],
      integration: new integrations.HttpLambdaIntegration('ApiIntegration', fn),
    });

    this.apiUrl = httpApi.apiEndpoint;

    new ssm.StringParameter(this, 'ApiUrlParam', {
      parameterName: '/claims/api-url',
      stringValue: this.apiUrl,
    });

    new cdk.CfnOutput(this, 'ApiUrl', { value: this.apiUrl });
  }
}
