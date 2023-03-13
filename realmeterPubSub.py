# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import argparse
import json
import logging
import os

import apache_beam as beam
import tensorflow as tf
from apache_beam.options.pipeline_options import PipelineOptions
from apache_beam.options.pipeline_options import SetupOptions
from beam_nuggets.io import relational_db

source_config = relational_db.SourceConfiguration(
    drivername='mysql',
    host='localhost',
    port=8080,
    username='usr',
    password='sofe4630u',
    database='smartmeter',
)

table_config = relational_db.TableConfiguration(
    name='readings',
    create_if_missing=True,
    primary_key_columns=['profile_name']
)

def singleton(cls):
  instances = {}
  def getinstance(*args, **kwargs):
    if cls not in instances:
      instances[cls] = cls(*args, **kwargs)
    return instances[cls]
  return getinstance


@singleton
class Model():

  def __init__(self, checkpoint):
    with tf.Graph().as_default() as graph:
      sess = tf.compat.v1.InteractiveSession()
      saver = tf.compat.v1.train.import_meta_graph(os.path.join(checkpoint, 'export.meta'))
      saver.restore(sess, os.path.join(checkpoint, 'export'))

      inputs = json.loads(tf.compat.v1.get_collection('inputs')[0])
      outputs = json.loads(tf.compat.v1.get_collection('outputs')[0])

      self.x = graph.get_tensor_by_name(inputs['profile_name'])
      self.p = graph.get_tensor_by_name(outputs['readings'])
      self.input_key = graph.get_tensor_by_name(inputs['key'])
      self.output_key = graph.get_tensor_by_name(outputs['key'])
      self.sess = sess


class PredictDoFn(beam.DoFn):

  def process(self, element, checkpoint):
    model = Model(checkpoint)

    time = str(element['time'])
    profile_name = str(element['profile_name'])
    temp = str(element['temperature'])
    humd = str(element['humidity'])
    pres = str(element['pressure'])

    attributes = {
      "time": time,
      "profile_name": profile_name,
      "temperature": temp,
      "humidity": humd,
      "pressure": pres
    };

    if (attributes['temperature']==" " or attributes['humidity']==" " or attributes['pressure']==" "):
      return
    else:
      return str(attributes)

            
def run(argv=None):
  parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('--input', dest='input', required=True,
                      help='Input file to process.')
  parser.add_argument('--output', dest='output', required=True,
                      help='Output file to write results to.')
  # parser.add_argument('--model', dest='model', required=True,
                      # help='Checkpoint file of the model.')
  known_args, pipeline_args = parser.parse_known_args(argv)
  pipeline_options = PipelineOptions(pipeline_args)
  pipeline_options.view_as(SetupOptions).save_main_session = True;
  
  with beam.Pipeline(options=pipeline_options) as p:
    profile_name = (p | "Read from Pub/Sub" >> beam.io.ReadFromPubSub(topic=known_args.input)
        | "toDict" >> beam.Map(lambda x: json.loads(x)));
        
    attributes = profile_name | 'Prediction' >> beam.ParDo(PredictDoFn(), known_args.model)
    
    (attributes | 'to byte' >> beam.Map(lambda x: json.dumps(x).encode('utf8'))
        |   'to Pub/sub' >> beam.io.WriteToPubSub(topic=known_args.output));

    profile_name = p | "Reading month records" >> beam.Create(profile_name)
    attributes | 'Writing to DB table' >> relational_db.Write(
      source_config=source_config,
      table_config=table_config
    )
if __name__ == '__main__':
  logging.getLogger().setLevel(logging.INFO)
  run()