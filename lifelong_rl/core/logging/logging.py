"""
Based on rllab's logger.

https://github.com/rll/rllab
"""
from enum import Enum
from contextlib import contextmanager
import numpy as np
import os
import os.path as osp
import sys
import datetime
import dateutil.tz
import csv
import json
import pickle
import errno
import torch
import wandb
import matplotlib.pyplot as plt
import tensorboardX as tbX

from lifelong_rl.core.logging.tabulate import tabulate


class TerminalTablePrinter(object):
    def __init__(self):
        self.headers = None
        self.tabulars = []

    def print_tabular(self, new_tabular):
        if self.headers is None:
            self.headers = [x[0] for x in new_tabular]
        else:
            assert len(self.headers) == len(new_tabular)
        self.tabulars.append([x[1] for x in new_tabular])
        self.refresh()

    def refresh(self):
        import os
        rows, columns = os.popen('stty size', 'r').read().split()
        tabulars = self.tabulars[-(int(rows) - 3):]
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.write(tabulate(tabulars, self.headers))
        sys.stdout.write("\n")


class MyEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, type):
            return {'$class': o.__module__ + "." + o.__name__}
        elif isinstance(o, Enum):
            return {
                '$enum': o.__module__ + "." + o.__class__.__name__ + '.' + o.name
            }
        elif callable(o):
            return {
                '$function': o.__module__ + "." + o.__name__
            }
        return json.JSONEncoder.default(self, o)


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


class Logger(object):
    def __init__(self):
        self.log_dir = ''
        self.log_to_wandb = False

        self._prefixes = []
        self._prefix_str = ''

        self._tabular_prefixes = []
        self._tabular_prefix_str = ''

        self._tabular = []
        self._fig = []
        self._video = []

        self._text_outputs = []
        self._tabular_outputs = []

        self._text_fds = {}
        self._tabular_fds = {}
        self._tabular_header_written = set()

        self._snapshot_dir = None
        self._snapshot_mode = 'all'
        self._snapshot_gap = 1

        self._log_tabular_only = False
        self._header_printed = False
        self.table_printer = TerminalTablePrinter()

        self._writer = None

        self._plt_figs = []

    def reset(self):
        self.__init__()

    def _add_output(self, file_name, arr, fds, mode='a'):
        if file_name not in arr:
            mkdir_p(os.path.dirname(file_name))
            arr.append(file_name)
            fds[file_name] = open(file_name, mode)

    def _remove_output(self, file_name, arr, fds):
        if file_name in arr:
            fds[file_name].close()
            del fds[file_name]
            arr.remove(file_name)

    def push_prefix(self, prefix):
        self._prefixes.append(prefix)
        self._prefix_str = ''.join(self._prefixes)

    def add_text_output(self, file_name):
        self._add_output(file_name, self._text_outputs, self._text_fds,
                         mode='a')

    def set_text_output(self, file_name):
        old_log_files = [old_file for old_file in self._text_fds]
        for old_file in old_log_files:
            self.remove_text_output(old_file)
        self.add_text_output(file_name)

    def remove_text_output(self, file_name):
        self._remove_output(file_name, self._text_outputs, self._text_fds)

    def add_tabular_output(self, file_name, relative_to_snapshot_dir=False):
        if relative_to_snapshot_dir:
            file_name = osp.join(self._snapshot_dir, file_name)
        self._add_output(file_name, self._tabular_outputs, self._tabular_fds,
                         mode='w')

    def set_tabular_output(self, file_name, relative_to_snapshot_dir=False):
        if relative_to_snapshot_dir:
            file_name = osp.join(self._snapshot_dir, file_name)
        old_log_files = [old_file for old_file in self._tabular_fds]
        for old_file in old_log_files:
            self.remove_tabular_output(old_file)
        self.add_tabular_output(file_name, relative_to_snapshot_dir=relative_to_snapshot_dir)

    def get_tabular_output(self, ind=0):
        return self._tabular_outputs[ind]

    def remove_tabular_output(self, file_name, relative_to_snapshot_dir=False):
        if relative_to_snapshot_dir:
            file_name = osp.join(self._snapshot_dir, file_name)
        if self._tabular_fds[file_name] in self._tabular_header_written:
            self._tabular_header_written.remove(self._tabular_fds[file_name])
        self._remove_output(file_name, self._tabular_outputs, self._tabular_fds)

    def set_tb(self, log_dir):
        self._writer = tbX.SummaryWriter(log_dir, flush_secs=120)

    def set_snapshot_dir(self, dir_name):
        self._snapshot_dir = dir_name

    def get_snapshot_dir(self, ):
        return self._snapshot_dir

    def get_snapshot_mode(self, ):
        return self._snapshot_mode

    def set_snapshot_mode(self, mode):
        self._snapshot_mode = mode

    def get_snapshot_gap(self, ):
        return self._snapshot_gap

    def set_snapshot_gap(self, gap):
        self._snapshot_gap = gap

    def set_log_tabular_only(self, log_tabular_only):
        self._log_tabular_only = log_tabular_only

    def get_log_tabular_only(self, ):
        return self._log_tabular_only

    def log(self, s, with_prefix=False, with_timestamp=True):
        out = s
        if with_prefix:
            out = self._prefix_str + out
        if with_timestamp:
            now = datetime.datetime.now(dateutil.tz.tzlocal())
            timestamp = now.strftime('%Y-%m-%d %H:%M:%S.%f %Z')
            out = "%s | %s" % (timestamp, out)
        if not self._log_tabular_only:
            # Also log to stdout
            print(out)
            for fd in list(self._text_fds.values()):
                fd.write(out + '\n')
                fd.flush()
            sys.stdout.flush()

    def record_tabular(self, key, val):
        self._tabular.append((self._tabular_prefix_str + str(key), str(val)))

    def record_fig(self, key, val):
        self._fig.append((self._tabular_prefix_str + str(key), val))

    def record_video(self, key, val):
        self._video.append((self._tabular_prefix_str + str(key), val))

    def record_dict(self, d, prefix=None):
        if prefix is not None:
            self.push_tabular_prefix(prefix)
        for k, v in d.items():
            self.record_tabular(k, v)
        if prefix is not None:
            self.pop_tabular_prefix()

    def push_tabular_prefix(self, key):
        self._tabular_prefixes.append(key)
        self._tabular_prefix_str = ''.join(self._tabular_prefixes)

    def pop_tabular_prefix(self, ):
        del self._tabular_prefixes[-1]
        self._tabular_prefix_str = ''.join(self._tabular_prefixes)

    def output_dir(self):
        return self._snapshot_dir

    def savefig(self, save_name, fig=None):
        orig_save_name = save_name
        save_name = self._snapshot_dir + '/' + save_name
        os.makedirs(os.path.dirname(save_name), exist_ok=True)
        plt.savefig(save_name)

        if False and self.log_to_wandb and fig is not None:
            data = np.fromstring(fig.canvas.tostring_rgb(), dtype=np.uint8, sep='')
            data = data.reshape(fig.canvas.get_width_height()[::-1] + (3,))

            # self._plt_figs.append(wandb.Image(data, caption=orig_save_name))

    def save_extra_data(self, data, file_name='extra_data.pkl', mode='joblib'):
        """
        Data saved here will always override the last entry

        :param data: Something pickle'able.
        """
        file_name = osp.join(self._snapshot_dir, file_name)
        if mode == 'joblib':
            import joblib
            joblib.dump(data, file_name, compress=3)
        elif mode == 'pickle':
            pickle.dump(data, open(file_name, "wb"))
        else:
            raise ValueError("Invalid mode: {}".format(mode))
        return file_name

    def get_table_dict(self, ):
        return dict(self._tabular)

    def get_table_key_set(self, ):
        return set(key for key, value in self._tabular)

    @contextmanager
    def prefix(self, key):
        self.push_prefix(key)
        try:
            yield
        finally:
            self.pop_prefix()

    @contextmanager
    def tabular_prefix(self, key):
        self.push_tabular_prefix(key)
        yield
        self.pop_tabular_prefix()

    def log_variant(self, log_file, variant_data):
        mkdir_p(os.path.dirname(log_file))
        with open(log_file, "w") as f:
            json.dump(variant_data, f, indent=2, sort_keys=True, cls=MyEncoder)

    def record_tabular_misc_stat(self, key, values, placement='back'):
        if placement == 'front':
            prefix = ""
            suffix = key
        else:
            prefix = key
            suffix = ""
        if len(values) > 0:
            self.record_tabular(prefix + "Average" + suffix, np.average(values))
            self.record_tabular(prefix + "Std" + suffix, np.std(values))
            self.record_tabular(prefix + "Median" + suffix, np.median(values))
            self.record_tabular(prefix + "Min" + suffix, np.min(values))
            self.record_tabular(prefix + "Max" + suffix, np.max(values))
        else:
            self.record_tabular(prefix + "Average" + suffix, np.nan)
            self.record_tabular(prefix + "Std" + suffix, np.nan)
            self.record_tabular(prefix + "Median" + suffix, np.nan)
            self.record_tabular(prefix + "Min" + suffix, np.nan)
            self.record_tabular(prefix + "Max" + suffix, np.nan)

    def dump_tabular(self, *args, **kwargs):
        wh = kwargs.pop("write_header", None)
        if len(self._tabular) > 0:
            if self._log_tabular_only:
                self.table_printer.print_tabular(self._tabular)
            else:
                for line in tabulate(self._tabular).split('\n'):
                    self.log(line, *args, **kwargs)

            tabular_dict = dict(self._tabular)
            fig_dict = dict(self._fig)
            video_dict = dict(self._video)

            # tb
            for key in tabular_dict:
                proc_key = key
                proc_key = proc_key.replace(' (s)', '')
                proc_key = proc_key.replace(' ', '_')
                proc_key = proc_key.lower()
                if '/' not in key or 'replay_buffer' in key:
                    proc_key = 'misc/' + proc_key
                value = float(tabular_dict[key])
                step = int(tabular_dict['exploration/num steps total'])
                self._writer.add_scalar(proc_key, value, step)
            for key in fig_dict:
                proc_key = key
                proc_key = proc_key.replace(' (s)', '')
                proc_key = proc_key.replace(' ', '_')
                proc_key = proc_key.lower()
                value = fig_dict[key]
                step = int(tabular_dict['Epoch'])
                self._writer.add_figure(proc_key, value, step)

            if self.log_to_wandb:
                # wandb_dict = {key: float(tabular_dict[key]) for key in tabular_dict}
                # wandb has issues
                wandb_dict = dict()
                for key in tabular_dict:
                    proc_key = key  # key.replace('/', '.')
                    proc_key = proc_key.replace(' (s)', '')
                    proc_key = proc_key.replace(' ', '_')
                    proc_key = proc_key.lower()
                    if '/' not in key or 'replay_buffer' in key:
                        proc_key = 'misc/' + proc_key
                    wandb_dict[proc_key] = float(tabular_dict[key])
                for key in fig_dict:
                    proc_key = key
                    proc_key = proc_key.replace(' (s)', '')
                    proc_key = proc_key.replace(' ', '_')
                    proc_key = proc_key.lower()
                    wandb_dict[proc_key] = wandb.Image(fig_dict[key])
                for key in video_dict:
                    proc_key = key
                    proc_key = proc_key.replace(' (s)', '')
                    proc_key = proc_key.replace(' ', '_')
                    proc_key = proc_key.lower()
                    wandb_dict[proc_key] = wandb.Video(video_dict[key])
                # wandb_dict['plt_imgs'] = self._plt_figs
                step = int(tabular_dict['Epoch'])
                wandb.log(wandb_dict, step=step)
                self._plt_figs = []

            # Also write to the csv files
            # This assumes that the keys in each iteration won't change!
            for tabular_fd in list(self._tabular_fds.values()):
                writer = csv.DictWriter(tabular_fd,
                                        fieldnames=list(tabular_dict.keys()))
                if wh or (
                        wh is None and tabular_fd not in self._tabular_header_written):
                    writer.writeheader()
                    self._tabular_header_written.add(tabular_fd)
                writer.writerow(tabular_dict)
                tabular_fd.flush()
            del self._tabular[:]
            del self._fig[:]
            del self._video[:]

    def pop_prefix(self, ):
        del self._prefixes[-1]
        self._prefix_str = ''.join(self._prefixes)

    def save_itr_params(self, itr, params, prefix='itr'):
        if self._snapshot_dir:
            if self._snapshot_mode == 'all':
                file_name = osp.join(self._snapshot_dir, '%s_%d.pt' % (prefix, itr))
                torch.save(params, file_name)
            elif self._snapshot_mode == 'last':
                # override previous params
                file_name = osp.join(self._snapshot_dir, 'params.pkl')
                torch.save(params, file_name)
            elif self._snapshot_mode == "gap":
                if itr % self._snapshot_gap == 0:
                    file_name = osp.join(self._snapshot_dir, 'itr_%d.pkl' % itr)
                    torch.save(params, file_name)
            elif self._snapshot_mode == "gap_and_last":
                if itr % self._snapshot_gap == 0:
                    file_name = osp.join(self._snapshot_dir, 'itr_%d.pkl' % itr)
                    torch.save(params, file_name)
                file_name = osp.join(self._snapshot_dir, 'params.pkl')
                torch.save(params, file_name)
            elif self._snapshot_mode == 'none':
                pass
            else:
                raise NotImplementedError


logger = Logger()
