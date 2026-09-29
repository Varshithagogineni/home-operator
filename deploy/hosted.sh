#!/usr/bin/env bash
# Home Operator, hosted on a public HTTPS link. Needs an `aws login` session to
# run - the hosted app itself never does; it signs with its own IAM role.
#
#   deploy/hosted.sh up       create or update everything, print the link
#   deploy/hosted.sh update   ship the current commit to the running server
#   deploy/hosted.sh code     print the access code to give judges
#   deploy/hosted.sh url      print the link
#   deploy/hosted.sh down     delete it all (the settings in SSM are kept)
set -euo pipefail

cd "$(dirname "$0")/.."
export AWS_REGION=us-east-1
STACK=home-operator-hosted
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=home-operator-deploy-$ACCOUNT
KEY=home-operator/app.tar.gz

settings() {
  # The same .env the laptop uses: Cognito client and the AgentCore URL.
  # Stored encrypted in SSM, read by the instance at start; never printed.
  aws ssm put-parameter --name /home-operator/env --type SecureString \
    --value "file://.env" --overwrite >/dev/null
  if ! aws ssm get-parameter --name /home-operator/access-code >/dev/null 2>&1; then
    local words=(amber birch cedar delta ember fable harbor iris juniper kestrel lumen maple nimbus orchid pebble quartz raven sierra tidal umber willow)
    local code="${words[RANDOM % ${#words[@]}]}-${words[RANDOM % ${#words[@]}]}-$((RANDOM % 90 + 10))"
    aws ssm put-parameter --name /home-operator/access-code --type SecureString --value "$code" >/dev/null
  fi
}

bundle() {
  # The committed code only: no .env, no manual PDFs, no audio cache.
  aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null || {
    aws s3api create-bucket --bucket "$BUCKET" >/dev/null
    aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  }
  local tmp; tmp=$(mktemp -d)
  git archive --format=tar.gz -o "$tmp/app.tar.gz" HEAD -- . ':!manuals' ':!media' ':!thumbnail.*' ':!homeoperator'
  aws s3 cp "$tmp/app.tar.gz" "s3://$BUCKET/$KEY" >/dev/null
  rm -rf "$tmp"
  echo "Uploaded $(git rev-parse --short HEAD)"
}

output() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

case "${1:-}" in
  up)
    settings
    bundle
    vpc=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
    subnet=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$vpc" Name=default-for-az,Values=true \
      Name=availability-zone,Values=us-east-1a --query 'Subnets[0].SubnetId' --output text)
    prefix=$(aws ec2 describe-managed-prefix-lists \
      --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
      --query 'PrefixLists[0].PrefixListId' --output text)
    aws cloudformation deploy --stack-name "$STACK" --template-file deploy/hosted.yaml \
      --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
      --parameter-overrides VpcId="$vpc" SubnetId="$subnet" CloudFrontPrefixList="$prefix" \
        ArtifactBucket="$BUCKET" ArtifactKey="$KEY"
    echo "Link: $(output Url)"
    ;;
  update)
    settings
    bundle
    id=$(output InstanceId)
    cmd=$(aws ssm send-command --instance-ids "$id" --document-name AWS-RunShellScript \
      --parameters commands=/usr/local/bin/ho-update --query Command.CommandId --output text)
    aws ssm wait command-executed --command-id "$cmd" --instance-id "$id" || true
    aws ssm get-command-invocation --command-id "$cmd" --instance-id "$id" --query Status --output text
    ;;
  code)
    aws ssm get-parameter --name /home-operator/access-code --with-decryption --query Parameter.Value --output text
    ;;
  url)
    output Url
    ;;
  down)
    aws cloudformation delete-stack --stack-name "$STACK"
    aws cloudformation wait stack-delete-complete --stack-name "$STACK"
    echo "Deleted. The access code and settings remain in SSM under /home-operator/."
    ;;
  *)
    sed -n '2,10p' "$0"
    exit 1
    ;;
esac
