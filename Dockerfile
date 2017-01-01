FROM python:3
MAINTAINER shaun@samsite.ca

VOLUME /root/.aws
VOLUME /code
ADD requirements.txt /code/requirements.txt
RUN pip install -r /code/requirements.txt

ADD example_specfile.yml /code/
ADD LICENSE /code/
ADD README.md /code/
ADD VERSION.txt /code/
ADD cfnbot /code/cfnbot
ADD setup.py /code/
RUN cd /code && python setup.py install

CMD cfnbot deploy /code/example_specfile.yml
