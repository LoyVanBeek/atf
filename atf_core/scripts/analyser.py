#!/usr/bin/env python
import json
import yaml
import os
import progressbar
import rosbag
import rostest
import sys
import time
import unittest

from atf_core import ATFConfigurationParser
from atf_msgs.msg import AtfResult, TestblockStatus, TestResult


class Analyser:
    def __init__(self, package_name):
        print "ATF analyser: started!"
        self.ns = "/atf/"
        self.error = False

        # parse configuration
        self.configuration_parser = ATFConfigurationParser(package_name)
        self.tests = self.configuration_parser.get_tests()
        #self.testblocks = self.configuration_parser.create_testblocks(self.config, None, True)

        #print "self.config", self.config
        #print "self.testblocks", self.testblocks

        # monitor states for all testblocks
        #self.testblock_states = {}
        #for testblock in self.testblocks.keys():
        #    self.testblock_states[testblock] = TestblockStatus.INVALID

        start_time = time.time()
        #self.files = self.config["test_name"]#"/tmp/atf_test_app_time/data/ts0_c0_r0_e0_0.bag" # TODO get real file names from test config
        #print "self.files", self.files
        #files = self.get_file_paths(os.path.dirname(self.files), os.path.basename(self.files))

        # generate results
        i = 1
        for test in self.tests:
            inputfile = os.path.join(test.generation_config["bagfile_output"] + test.name + ".bag")
            print "Processing test %i/%i: %s"%(i,len(self.tests),test.name)
            try:
                bag = rosbag.Bag(inputfile)
            except rosbag.bag.ROSBagException as e:
                print "ERROR empty bag file", e
                i += 1
                continue
            if bag.get_message_count() == 0:
                print "ERROR empty bag file"
                i += 1
                continue
            bar = progressbar.ProgressBar(maxval=bag.get_message_count(), \
                    widgets=[progressbar.Bar('=', '[', ']'), ' ', progressbar.Percentage()])
            bar.start()
            j=0
            count_error=0

            try:
                for topic, raw_msg, t in bag.read_messages(raw=True):
                    try:
                        msg_type, serialized_bytes, md5sum, pos, pytype = raw_msg
                        msg = pytype()
                        msg.deserialize(serialized_bytes)
                        j+=1
                        for testblock in test.testblocks:
                            #print "testblock", testblock.name
                            #print "testblock.metric_handles", testblock.metric_handles
                            for metric_handle in testblock.metric_handles:
                                if topic == "/atf/status" and msg.name == testblock.name:
                                    #print "topic match for testblock '%s'"%testblock.name
                                    #print "testblock status for testblock '%s':"%testblock.name, testblock.status
                                    testblock.status = msg.status
                                    if testblock.status == TestblockStatus.ACTIVE:
                                        #print "calling start on metric", metric_handle
                                        metric_handle.start(msg)
                                    elif testblock.status == TestblockStatus.SUCCEEDED:
                                        #print "calling stop on metric", metric_handle
                                        metric_handle.stop(msg)
                                else:
                                    metric_handle.update(topic, msg, t)
                    #bar.update(j)
                    except StopIteration as e:
                        print "stop iterator", e
                        break
                    except Exception as e:
                        print "Exception", e
                        count_error += 1
                        continue
            except Exception as e:
                print "FATAL exception in bag file", type(e), e
                continue
            bar.finish()

            

            print "%d errors detected during test processing"%count_error
            i += 1
        
        #export test list
        test_list = self.configuration_parser.get_test_list()
        self.configuration_parser.export_to_file(test_list, os.path.join(test.generation_config["txt_output"], "test_list.txt"))
        #self.configuration_parser.export_to_file(test_list, os.path.join(test.generation_config["json_output"], "test_list.json"))
        #self.configuration_parser.export_to_file(test_list, os.path.join(test.generation_config["yaml_output"], "test_list.yaml"))

        try:
            print "Processing tests took %s min"%str( round((time.time() - start_time)/60.0,4 ))
        except:
            pass

        print "ATF analyser: done!"

    def get_file_paths(self, dir, prefix):
        result = []
        for subdir, dirs, files in os.walk(dir):
            for file in files:
                full_path = os.path.join(subdir, file)
                if file.startswith(prefix):
                    result.append((file,full_path))
        result.sort()
        return result

    def get_result(self):
        atf_result = AtfResult()
        atf_result.header.stamp = time.time()
        atf_result.groundtruth_result = None
        atf_result.groundtruth_error_message = "Failed ATF tests:"
        for test in self.tests:
            # get result
            test_result = test.get_result()
            
            # export overall test result to file
            self.configuration_parser.export_to_file(test_result, os.path.join(test.generation_config["txt_output"], test.name + ".txt"))
            #self.configuration_parser.export_to_file(test_result, os.path.join(test.generation_config["json_output"], test.name + ".json")) # ROS message object is not JSON serialisable
            #self.configuration_parser.export_to_file(test_result, os.path.join(test.generation_config["yaml_output"], test.name + ".yaml")) # ROS message object is not correctly serialized to yaml

            # append result
            atf_result.results.append(test_result)
            
            # aggregate result
            if test_result.groundtruth_result != None and not test_result.groundtruth_result:
                atf_result.groundtruth_result = False
                atf_result.groundtruth_error_message += "\n - test '%s': %s"%(test_result.name, test_result.groundtruth_error_message)
                #print atf_result.groundtruth_error_message
            if atf_result.groundtruth_result == None and test_result.groundtruth_result:
                atf_result.groundtruth_result = True

        if len(atf_result.results) == 0:
            raise ATFAnalyserError("Analysing failed, no atf result available.")

        #print "\natf_result:\n", atf_result
        return atf_result
    
    def print_result(self, atf_result):
        if atf_result.groundtruth_result != None and not atf_result.groundtruth_result:
            print "\n"
            print "*************************"
            print "*** SOME TESTS FAILED ***"
            print "*************************"
            print atf_result.groundtruth_error_message
        else:
            print "\n"
            print "********************"
            print "*** ALL TESTS OK ***"
            print "********************"
            print "\n"

    def print_result_details(self, atf_result):
        print "\n"
        print "**********************"
        print "*** result details ***"
        print "**********************"
        print atf_result

class ATFAnalyserError(Exception):
    pass


class TestAnalysing(unittest.TestCase):
    def test_Analysing(self):
        analyser = Analyser(sys.argv[1])
        atf_result = analyser.get_result()
        analyser.print_result(atf_result)
        #analyser.print_result(atf_result)
        if atf_result.groundtruth_result != None:
            self.assertTrue(atf_result.groundtruth_result, atf_result.groundtruth_error_message)

if __name__ == '__main__':
    print "analysing for package", sys.argv[1]
    if "standalone" in sys.argv:
        analyser = Analyser(sys.argv[1])
        atf_result = analyser.get_result()
        analyser.print_result(atf_result)
        #analyser.print_result_details(atf_result)

    else:
        rostest.rosrun("atf_core", 'analysing', TestAnalysing, sysargs=sys.argv)
