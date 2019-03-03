import tensorflow as tf
import numpy as np
import argparse
import socket
import importlib
import time
import os
import scipy.misc
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, 'models'))
sys.path.append(os.path.join(BASE_DIR, 'utils'))
import provider
import pc_util


parser = argparse.ArgumentParser()
parser.add_argument('--gpu', type=int, default=0, help='GPU to use [default: GPU 0]')
parser.add_argument('--model', default='dgcnn', help='Model name: dgcnn [default: dgcnn]')
parser.add_argument('--batch_size', type=int, default=100, help='Batch Size during training [default: 1]')
parser.add_argument('--num_point', type=int, default=512, help='Point Number [256/512/1024/2048] [default: 1024]')
parser.add_argument('--model_path', default='log/model.ckpt', help='model checkpoint file path [default: log/model.ckpt]')
parser.add_argument('--dump_dir', default='dump', help='dump folder path [dump]')
parser.add_argument('--visu', action='store_true', help='Whether to dump image for error case [default: False]')
FLAGS = parser.parse_args()


BATCH_SIZE = FLAGS.batch_size
NUM_POINT = FLAGS.num_point
MODEL_PATH = FLAGS.model_path
GPU_INDEX = FLAGS.gpu
MODEL = importlib.import_module(FLAGS.model) # import network module
DUMP_DIR = FLAGS.dump_dir
if not os.path.exists(DUMP_DIR): os.mkdir(DUMP_DIR)
LOG_FOUT = open(os.path.join(DUMP_DIR, 'log_evaluate.txt'), 'w')
LOG_FOUT.write(str(FLAGS)+'\n')

NUM_CLASSES = 2
SHAPE_NAMES = [line.rstrip() for line in \
    open(os.path.join(BASE_DIR, 'data/modelnet40_ply_hdf5_2048_cut/shape_names.txt'))]

HOSTNAME = socket.gethostname()

# ModelNet40 official train/test split
TRAIN_FILES = provider.getDataFiles(\
    os.path.join(BASE_DIR, 'data/modelnet40_ply_hdf5_2048_cut/train_files.txt'))
TEST_FILES = provider.getDataFiles(\
    os.path.join(BASE_DIR, 'data/modelnet40_ply_hdf5_2048_cut/test_files.txt'))

def log_string(out_str):
    LOG_FOUT.write(out_str+'\n')
    LOG_FOUT.flush()
    print(out_str)

def evaluate(num_votes):
    is_training = False

    with tf.device('/gpu:'+str(GPU_INDEX)):
        pointclouds_pl, labels_pl = MODEL.placeholder_inputs(BATCH_SIZE, NUM_POINT)
        is_training_pl = tf.placeholder(tf.bool, shape=())
        # simple model
        pred, feature1, feature2, end_points = MODEL.get_model(pointclouds_pl, pointclouds_pl, is_training_pl)
        loss = MODEL.get_constra_loss(feature1, feature2, labels_pl, end_points)
        # Add ops to save and restore all the variables.
        saver = tf.train.Saver()

    # Create a session
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    config.allow_soft_placement = True
    config.log_device_placement = True
    sess = tf.Session(config=config)

    # Restore variables from disk.
    saver.restore(sess, MODEL_PATH)
    log_string("Model restored.")
    ops = {'pointclouds_pl': pointclouds_pl,
           'labels_pl': labels_pl,
           'is_training_pl': is_training_pl,
           'pred': pred,
           'loss': loss,
           'feature': feature1}

    #save labels for test
    feature_f = open('feature.txt', 'w+')
    eval_one_epoch(sess, ops,feature_f, num_votes)

def eval_one_epoch(sess, ops, feature_f, num_votes=1, topk=1):
    error_cnt = 0
    is_training = False
    total_correct = 0
    total_seen = 0
    loss_sum = 0
    total_seen_class = [0 for _ in range(NUM_CLASSES)]
    total_correct_class = [0 for _ in range(NUM_CLASSES)]
    fout = open(os.path.join(DUMP_DIR, 'pred_label.txt'), 'w')

    current_data = np.empty([len(TEST_FILES), NUM_POINT, 3], dtype=float)
    labels  =  np.empty([len(TEST_FILES),1], dtype=int)
    current_label  =  np.empty([len(TEST_FILES),1], dtype=int)

    for fn in range(len(TEST_FILES)):
        # log_string('----'+str(fn)+'----')
        cut1, cut2, label = provider.loadDataFile_cut_2(TEST_FILES[fn], False)
        data = np.concatenate((cut1, cut2), axis=0)
        # data = cut1
        #
        # cut1, cut2, cut3, cut4, label = provider.loadDataFile_cut_4(TEST_FILES[fn], False)
        # data = np.concatenate((cut1, cut2, cut3, cut4), axis=0)

        # total, label = provider.loadDataFile_cut(TEST_FILES[fn])
        # data = np.concatenate((total[0], total[1], total[2], total[3], total[4], total[5], total[6], total[7]), axis=0)

        idx = np.random.randint(data.shape[0], size=NUM_POINT)
        data = data[idx,:]

        label = np.squeeze(label)
        current_data[fn] = data
        current_label[fn] = 0
        labels[fn] = label

    current_label = np.squeeze(current_label)
    #save labels for test
    label_f =  open('label.txt', 'w+')

    np.savetxt(label_f, labels, fmt='%d')

    file_size = current_data.shape[0]
    num_batches = file_size // BATCH_SIZE
    print(file_size)

    for batch_idx in range(num_batches):
        start_idx = batch_idx * BATCH_SIZE
        end_idx = (batch_idx+1) * BATCH_SIZE
        cur_batch_size = end_idx - start_idx

        for vote_idx in range(num_votes):
            rotated_data = provider.rotate_point_cloud_by_angle(current_data[start_idx:end_idx, :, :],
                                              vote_idx/float(num_votes) * np.pi * 2)
            feed_dict = {ops['pointclouds_pl']: rotated_data,
                         ops['labels_pl']: current_label[start_idx:end_idx],
                         ops['is_training_pl']: is_training}

            loss_val, pred_val, feat_out = sess.run([ops['loss'], ops['pred'], ops['feature']],
                                      feed_dict=feed_dict)
            feat_sum = tf.math.add(feat_sum, feat_out)

        feat_avg = sess.run(tf.constant(feat_sum))
        feat_avg = feat_avg / num_votes
        np.savetxt(feature_f, feat_avg, fmt='%f')

if __name__=='__main__':
    with tf.Graph().as_default():
        evaluate(num_votes=12)
    LOG_FOUT.close()