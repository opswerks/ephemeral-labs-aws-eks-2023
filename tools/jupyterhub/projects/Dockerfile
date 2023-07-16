FROM jupyterhub/k8s-singleuser-sample:2.0.0
USER root

# Installing other needed tools, like git via APT
RUN apt-get update -y && \
    apt-get install -y \
    vim \
    build-essential \
    unzip \
    curl \
    openssl \
    git \
    nodejs \
    npm

# Installing AWS CLI and setup configuration
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
RUN unzip awscliv2.zip
RUN ./aws/install

# Installing kubectl
ENV KUBECTL_RELEASE=1.25.0
RUN curl -LO https://storage.googleapis.com/kubernetes-release/release/v${KUBECTL_RELEASE}/bin/linux/amd64/kubectl && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl

# Installing Jupyer extensions/plugins/etc...
RUN pip3 install --no-cache jupyter_contrib_nbextensions
RUN pip3 install --upgrade jupyterthemes
RUN pip3 install --upgrade jupyterlab-git
RUN jupyter lab build

# Clean apt cache, AWS CLI installer adn PIP
RUN apt-get clean && \
    apt-get autoremove --yes
RUN rm -Rfv ./aws ./awscliv2.zip
RUN rm -Rfv /root/.cache/pip

# Defaults
ENV NB_USER=jovyan \
    NB_UID=1000 \
    HOME=/home/jovyan

WORKDIR ${HOME}
USER ${NB_USER}

# Setup AWS configuration
RUN mkdir ${HOME}/.aws/ && touch ${HOME}/.aws/config && chmod 600 ${HOME}/.aws/config
RUN echo '[default]\n\
region = us-west-2\n\
output = json\n\
credential_source = Ec2InstanceMetadata' > ${HOME}/.aws/config

EXPOSE 8888
ENTRYPOINT ["tini", "--"]
CMD ["jupyter", "lab"]