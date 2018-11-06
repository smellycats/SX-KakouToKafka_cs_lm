# -*- coding: utf-8 -*-
import time
import json
import base64
import socket

import arrow

import helper
from helper_consul import ConsulAPI
from helper_kakou_cs_lm_v2 import Kakou
from helper_kafka_producer import KafkaProducer
from my_yaml import MyYAML
from my_logger import *


debug_logging('/home/logs/error.log')
logger = logging.getLogger('root')


class UploadData(object):
    def __init__(self):
        # 配置文件
        self.my_ini = MyYAML('/home/my.yaml').get_ini()

        # request方法类
        self.kk = None
        self.kp = KafkaProducer(**dict(self.my_ini['kafka']))
        self.con = ConsulAPI()
        self.con.path = dict(self.my_ini['consul'])['path']
	
        # ID上传标记
        self.kk_name = dict(self.my_ini['kakou'])['name']
        self.step = dict(self.my_ini['kakou'])['step']
        self.kkdd = dict(self.my_ini['kakou'])['kkdd']

        #self.uuid = None                    # session id
        #self.session_time = time.time()     # session生成时间戳
        #self.ttl = dict(self.my_ini['consul'])['ttl']               # 生存周期
        #self.lock_name = dict(self.my_ini['consul'])['lock_name']   # 锁名

        self.local_ip = socket.gethostbyname(socket.gethostname())  # 本地IP
        self.maxid = 0

        #self.id_flag = self.flag_ini.get_ini()['id']

    def get_id(self):
        """获取上传id"""
        r = self.con.get_id()[0]
        return base64.b64decode(r['Value']).decode(), r['ModifyIndex']

    def set_id(self, _id, modify_index):
        """设置ID"""
        if self.con.put_id(_id, modify_index):
            print(_id)

    def post_lost_data(self):
        """未上传数据重传"""
        lost_list, modify_index = self.get_lost()
        if len(lost_list) == 0:
            return 0
        t = arrow.now('PRC').format('YYYY-MM-DD HH:mm:ss')
        for i in lost_list:
            value = {'timestamp': t, 'message': i['message']}
            self.ka.produce_info(key='{0}_{0}'.format(self.kk_name, i['message']['id']), value=json.dumps(value))
            print('lost={0}'.format(i['message']['id']))
        self.ka.flush()
        lost_list = []
        if len(self.ka.lost_msg) > 0:
            for i in self.ka.lost_msg:
                lost_list.append(json.loads(i.value()))
            self.ka.lost_msg = []
        self.con.put_lost(json.dumps(lost_list))
        return len(lost_list)

    def post_info(self):
        """上传数据"""
        t, modify_index = self.get_id()
        st = arrow.get(t).replace(seconds=1).format('YYYY-MM-DD HH:mm:ss')
        et = arrow.get(t).replace(hours=2).format('YYYY-MM-DD HH:mm:ss')
        info = self.kk.get_kakou(st, et, 1, self.step+1)
        #print(info['total_count'])
        # 如果查询数据为0
        if info['total_count'] == 0:
            mt = self.kk.get_maxtime()['maxtime']
            if arrow.get(et).timestamp < arrow.get(mt).timestamp:
                self.set_id(et, modify_index)
            return 0

        lost_msg = []  #未上传数据列表
        def acked(err, msg):
            if err is not None:
                lost_msg.append(msg.value().decode('utf-8'))
                logger.error(msg.value())
                logger.error(err)
        t = arrow.now('PRC').format('YYYY-MM-DD HH:mm:ss')
        for i in info['items']:
            i['cllx'] = 'X99'
            i['csys'] = 'Z'
            i['hpzl'] = helper.hphm2hpzl(i['hphm'], i['hpys_id'], i['hpzl'])
            value = {'timestamp': t, 'message': i}
            self.kp.produce_info(key='{0}_{0}'.format(self.kk_name, i['id']), value=json.dumps(value), cb=acked)
        self.kp.flush()
        if len(lost_msg) > 0:
            return 0
        self.set_id(info['items'][0]['jgsj'], modify_index)
        return info['total_count']

    def main_loop(self):
        while 1:
            if self.kk is not None and self.kk.status:
                try:
                    #m = self.post_lost_data()
                    #if m > 0:
                    #    time.sleep(0.5)
                    #    continue
                    n = self.post_info()
                    if n < self.step:
                        time.sleep(1)
                except Exception as e:
                    logger.exception(e)
                    time.sleep(15)
            else:
                try:
                    if self.kk is None or not self.kk.status:
                        self.kk = Kakou(**dict(self.my_ini['kakou']))
                        self.kk.status = True
                except Exception as e:
                    logger.error(e)
                    time.sleep(1)
        
