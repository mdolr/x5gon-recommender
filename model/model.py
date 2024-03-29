# Based on https://github.com/pyg-team/pytorch_geometric/blob/master/examples/hetero/hetero_link_pred.py
# and https://github.com/pyg-team/pytorch_geometric/issues/3958

import argparse
import os.path as osp
import sys
import traceback

import numpy as np

import torch
import torch.nn.functional as F
from torch.nn import Linear, Softmax

import torch_geometric.transforms as T
from torch_geometric.nn import GATConv, SuperGATConv, SAGEConv, GATv2Conv, GCNConv, to_hetero
from torchsummary import summary

import matplotlib.pyplot as plt

import pickle


data = None
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

with open('../data/datav3.pkl', 'rb') as pickle_file:
    data = pickle.load(pickle_file)

    data['materials']['x'] = data['materials']['x'].to(torch.float32)
    data['concepts']['x'] = data['concepts']['x'].to(torch.float32)
    data['materials', 'links', 'concepts']['edge_index'] = data['materials',
                                                                'links', 'concepts']['edge_index'].to(torch.int64)
    data['materials', 'links', 'concepts']['edge_label'] = data['materials',
                                                                'links', 'concepts']['edge_label'].to(torch.long)
    data['materials', 'links', 'concepts']['edge_label'] = data['materials',
                                                                'links', 'concepts']['edge_label'].add(0)

# path = osp.join(osp.dirname(osp.realpath(__file__)), '../../data/MovieLens')
# dataset = MovieLens(path, model_name='all-MiniLM-L6-v2')
# data = dataset[0].to(device)

# Add a reverse ('movie', 'rev_rates', 'user') relation for message passing:
data = T.ToUndirected()(data)

"""
data['materials', 'links', 'concepts']['edge_label'] = data['materials',
                                                            'links', 'concepts']['edge_label'].long()
data['concepts', 'rev_links', 'materials']['edge_label'] = data['concepts',
                                                                'rev_links', 'materials']['edge_label'].long()
"""
# del data['movie', 'rev_rates', 'user'].edge_label  # Remove "reverse" label.
# print(data['materials', 'links', 'concepts'].edge_label.shape)
# Perform a link-level split into training, validation, and test edges:
train_data, val_data, test_data = T.RandomLinkSplit(
    num_val=0.1,
    num_test=0.1,
    neg_sampling_ratio=1.0,
    add_negative_train_samples=True,
    is_undirected=True,
    edge_types=[('materials', 'links', 'concepts')],
    rev_edge_types=[('concepts', 'rev_links', 'materials')],
)(data)

# print(train_data['materials', 'links', 'concepts'].edge_label.shape,
#      train_data['materials', 'links', 'concepts'].edge_label)


loss_function = torch.nn.CrossEntropyLoss()


class GNNEncoder(torch.nn.Module):
    def __init__(self, hidden_channels, out_channels):
        super().__init__()
        self.conv1 = SAGEConv((-1, -1), hidden_channels)
        self.conv2 = SAGEConv((-1, -1), out_channels)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index).relu()
        x = self.conv2(x, edge_index)
        return x


class EdgeDecoder(torch.nn.Module):
    def __init__(self, out_channels):
        super().__init__()
        # 2 * hidden_channels because we have applied to_hetero
        # with the parameter aggr='sum' which has led to making
        # a 2 * hidden_channels tensor
        self.lin1 = Linear(2 * out_channels, out_channels)

        # Return a tensor with 2 outputs, one for existing edges
        # the other for non-existing edges
        self.lin2 = Linear(out_channels, 2)

        # Return a softmax of z so we can
        # use it as a probability distribution
        self.softmax = Softmax(dim=-1)

    def forward(self, z_dict, edge_label_index):
        row, col = edge_label_index
        z = torch.cat([z_dict['materials'][row],
                       z_dict['concepts'][col]], dim=-1)
        k = z
        z = self.lin1(z).relu()
        z = self.lin2(z)

        # Return the softmax of the output
        return self.softmax(z), k


class Model(torch.nn.Module):
    def __init__(self, hidden_channels, out_channels):
        super().__init__()
        self.encoder = GNNEncoder(hidden_channels, out_channels)
        self.encoder = to_hetero(self.encoder, data.metadata(), aggr='sum')
        self.decoder = EdgeDecoder(out_channels)

    def forward(self, x_dict, edge_index_dict, edge_label_index):
        z_dict = self.encoder(x_dict, edge_index_dict)
        probabilities, k = self.decoder(z_dict, edge_label_index)
        return probabilities, z_dict, k


model = Model(hidden_channels=64, out_channels=32).to(device)

# Due to lazy initialization, we need to run one model step so the number
# of parameters can be inferred:


with torch.no_grad():
    try:
        model.encoder(train_data.x_dict, train_data.edge_index_dict)
    except AssertionError:
        _, _, tb = sys.exc_info()
        traceback.print_tb(tb)  # Fixed format
        tb_info = traceback.extract_tb(tb)
        filename, line, func, text = tb_info[-1]

        print('An error occurred on line {} in statement {}'.format(line, text))
        exit(1)

optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

print(model)


def train():
    model.train()
    optimizer.zero_grad()

    # Get outputs from the model
    pred, _1, _2 = model(train_data.x_dict, train_data.edge_index_dict,
                         train_data['materials', 'links', 'concepts'].edge_label_index)  # train_data['materials', 'concepts'].edge_label_index

    # Predictions by the model are tensors where the sum of probabilities = 1
    # we just get the argmax from those tensors for each prediction
    # pred = torch.argmax(pred, dim=1)

    # We get the real value we should be predicting (1=exists, 0=does not exist)
    target = train_data['materials', 'links',
                        'concepts'].edge_label.to(torch.long)
    target = torch.nn.functional.one_hot(target).to(torch.float)

    # Calculate the loss
    loss = loss_function(pred, target)

    loss.backward()
    optimizer.step()
    return float(loss)


@torch.no_grad()
def test(data):
    model.eval()
    pred, _1, _2 = model(data.x_dict, data.edge_index_dict,
                         data['materials', 'links', 'concepts'].edge_label_index)
    # pred = pred.clamp(min=0, max=5)
    target = data['materials', 'links', 'concepts'].edge_label.long()
    target = torch.nn.functional.one_hot(target).to(torch.float)

    # Calculate the loss
    loss = loss_function(pred, target)

    # loss.backward()
    return float(loss)


"""
@torch.no_grad()
def test(data):
    model.eval()
    pred = model(data.x_dict, data.edge_index_dict,
                 data['materials', 'links', 'concepts'].edge_label_index)
    pred = pred.clamp(min=0, max=5)
    target = data['materials', 'links', 'concepts'].edge_label.long()
    target = torch.nn.functional.one_hot(target).to(torch.float)
    rmse = F.mse_loss(pred, target).sqrt()
    return float(rmse)
"""

EPOCHS = 300  # 300
current_epoch = 0
loss_train = None
loss_val = None
loss_test = None
loss = None

losses = []

for epoch in range(1, EPOCHS):
    loss = train()
    loss_train = test(train_data)
    loss_val = test(val_data)
    loss_test = test(test_data)

    print(f'Epoch: {epoch:03d}, Loss: {loss:.4f}, Train: {loss_train:.4f}, '
          f'Val: {loss_val:.4f}, Test: {loss_test:.4f}')

    losses.append({'epoch': epoch, 'training': loss, 'test_training': loss_train,
                  'test_val': loss_val, 'test_test': loss_test})

    current_epoch = epoch

torch.save({
    'epoch': current_epoch,
    'model_state_dict': model.state_dict(),
    'optimizer_state_dict': optimizer.state_dict(),
    'loss': loss,
}, './model.pt')

activation = {}

metrics = ['training', 'test_val', 'test_test']
for metric in metrics:
    plt.plot(range(len(losses)), [x[metric] for x in losses])

plt.legend(metrics)
plt.title('Metric evolution')
plt.xlabel('Epochs')
plt.ylabel('Cross Entropy loss')
plt.show()


def get_activation(name):
    def hook(model, input, output):
        activation[name] = output.detach()
    return hook


print('Recuperation de la couche n-1 du modele')
model.encoder.conv2.register_forward_hook(get_activation('conv2'))
output, z_dict, k = model(train_data.x_dict, train_data.edge_index_dict,
                          train_data['materials', 'links', 'concepts'].edge_label_index)

print(k.shape)
print(z_dict, z_dict['materials'].shape)
"""
model.encoder.conv2.register_forward_hook(get_activation('conv2'))
output = model(train_data.x_dict, train_data.edge_index_dict,
               train_data['materials', 'links', 'concepts'].edge_label_index)
print(output)
"""
