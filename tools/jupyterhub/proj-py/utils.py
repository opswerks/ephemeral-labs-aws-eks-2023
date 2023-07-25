import pulumi
import json
from subprocess import run, PIPE

# Load static needed details
config = pulumi.Config()
data = config.require_object("details")

# Retrieve secrets in 1password
try:
    op_init = run(["op", "signin"], stdout=PIPE, stderr=PIPE, text=True)
    gh_client_id = json.loads(run(["op", "--vault",
                        f"{data.get('vault')}",
                        "item", "get",
                        f"{data.get('item')}",
                        "--field", "username",
                        "--format", "json"],
                        stdout=PIPE, stderr=PIPE, text=True).stdout)["value"]
    gh_client_secret = json.loads(run(["op", "--vault",
                            f"{data.get('vault')}",
                            "item", "get",
                            f"{data.get('item')}",
                            "--field", "password",
                            "--format", "json"],
                            stdout=PIPE, stderr=PIPE, text=True).stdout)["value"]
except Exception as e:
    print(f"OP CLI failed due to {e}")
    exit(1)


# Generate kubeconfig for K8s Provider
def generate_kube_config(server, cert, token):

    kubeconfig = json.dumps({
        "apiVersion": "v1",
        "clusters": [{
            "cluster": {
                "server": f"{server}",
                "certificate-authority-data": f"{cert}"
            },
            "name": "kubernetes",
        }],
        "contexts": [{
            "context": {
                "cluster": "kubernetes",
                "user": "data-group-token-user",
            },
            "name": "data-group",
        }],
        "current-context": "data-group",
        "kind": "Config",
        "users": [{
            "name": "data-group-token-user",
            "user": {
                "token": f"{token}",
            },
        }],
    })

    return kubeconfig

# Template content for values.yml
values_tpl ='''
hub:
  config:
    JupyterHub:
      admin_access: True
      allow_named_servers: True  
      cleanup_servers: True
      cleanup_proxy: True
      concurrent_spawn_limit: 5
      shutdown_on_logout: True
  extraEnv:
    - name: OAUTH_CALLBACK_URL
      value: https://{app_name}-{lab_name}.{dns_zone}/hub/oauth_callback
    - name: GITHUB_CLIENT_ID
      valueFrom:
        secretKeyRef:
          name: {secret_name}
          key: id
    - name: GITHUB_CLIENT_SECRET
      valueFrom:
        secretKeyRef:
          name: {secret_name}
          key: secret
  extraConfig:
    extra_config.py: |
      c.Spawner.start_timeout = 300  
      c.JupyterHub.authenticator_class = 'github'
      c.GitHubOAuthenticator.client_id = os.environ['GITHUB_CLIENT_ID']
      c.GitHubOAuthenticator.client_secret = os.environ['GITHUB_CLIENT_SECRET']
      c.GitHubOAuthenticator.oauth_callback_url = os.environ['OAUTH_CALLBACK_URL']
      c.GitHubOAuthenticator.allowed_organizations = ['{git_org}']
      c.GitHubOAuthenticator.scope = ['read:org']
      c.Authenticator.admin_users = {{'jpperdon'}}
      c.KubeSpawner.enable_user_namespaces = True
      c.KubeSpawner.user_namespace_template = u'lab-{{username}}'
      c.KubeSpawner.environment = {{
          'JUPYTERHUB_API_URL': 'http://hub.{hub_ns}.svc.cluster.local:8081/hub/api'
      }}      
      c.KubeSpawner.profile_list = [
        {{
            'display_name': 'A1T-ITN1: Introduction to Networks',
            'description': 'A list of exercise(s) to understand the basic(s) of Networks through the CLI',
            'slug': 'a1t-itn1-exercises',
            'default': True,
            'profile_options': {{
                'module': {{
                    'display_name': 'Module(s)',
                    'choices': {{
                        'curl': {{
                            'display_name': 'API Basic(s) through Curl',
                            'kubespawner_override': {{'mem_limit': '1G'}},
                        }},
                        'openssl': {{
                            'display_name': 'SSL/TLS/mTLS Basic(s) through OpenSSL',
                            'kubespawner_override': {{'mem_limit': '2G'}},
                        }}    
                    }}    
                }}
            }}
        }},
        {{
            'display_name': 'AWS Community 2023: Ephemeral Labs Demo',
            'description': 'A list of exercise(s) to demo Ephemeral Labs',
            'slug': 'aws-community-2023-exercises',
            'profile_options': {{
                'module': {{
                    'display_name': 'Module(s)',
                    'choices': {{
                        'aws_demo': {{
                            'display_name': 'Curl/OpenSSL/AWSCLI Exercise(s)',
                            'kubespawner_override': {{'mem_limit': '2G'}},
                        }}    
                    }}    
                }}
            }}
        }}        
      ]      
  serviceAccount:
    create: false
    name: {svc_account}-svc-account     
singleuser:
  image:
    name: {repo_url}
    tag: latest
    pullPolicy: IfNotPresent
    pullSecrets:
      - regcred
  serviceAccountName: {usr_svc_account}-svc-account
  cloudMetadata:
    blockWithIptables: false
  allowPrivilegeEscalation: true
  lifecycleHooks:
    postStart:
      exec:
        command:
        - "sh"
        - "-c"
        - >
           git clone https://github.com/jpperdon/sample-notebooks.git AWS-Community-2023_Ephemeral-Labs-Demo || true     
prePuller:
  hook:
    enabled: false
proxy:
  service:
    type: NodePort
cull:
  maxAge: 604800
debug:
  enabled: true    
'''