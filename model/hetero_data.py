import torch
import pandas as pd
from torch_geometric.data import HeteroData
import pickle

concepts_path = '../data/corrected_latent_concepts.csv'
materials_path = '../data/latent_materials.csv'
links_path = '../data/corrected_links_short.csv'


def load_node_csv(path, index_col, encoders=None, selected_indexes=[], **kwargs):
    df = pd.read_csv(path, index_col=index_col, **kwargs)

    mapping = {i: index for i, index in enumerate(df.index.unique())}

    """
    if len(selected_indexes) > 0:
        df = df.iloc[selected_indexes]
        print(df)

        mapping = {i: index for i, index in enumerate(df.index.unique())}
    """

    x = torch.tensor(df.values, dtype=torch.double)
    # x = x.to(torch.double)

    if encoders is not None:
        xs = [encoder(df[col]) for col, encoder in encoders.items()]
        x = torch.cat(xs, dim=-1)

    return x, mapping


def load_edge_csv(path, src_index_col, src_mapping, dst_index_col, dst_mapping,
                  encoders=None, **kwargs):
    df = pd.read_csv(path, **kwargs)

    src = [src_mapping[index] for index in df[src_index_col]]
    dst = [dst_mapping[index] for index in df[dst_index_col]]

    edge_index = torch.tensor([src, dst], dtype=torch.double)
    # edge_index = edge_index.to(torch.double)

    edge_attr = torch.tensor(df['target'], dtype=torch.double)
    # edge_attr = edge_attr.to(torch.double)

    if encoders is not None:
        edge_attrs = [encoder(df[col]) for col, encoder in encoders.items()]
        edge_attr = torch.cat(edge_attrs, dim=-1)

    return edge_index, edge_attr


print('Loading materials')
materials, materials_mapping = load_node_csv(
    materials_path, index_col=0)

print('Loading concepts')
links = pd.read_csv(links_path, index_col=0)

concepts, concepts_mapping = load_node_csv(
    concepts_path, index_col=0)  # , selected_indexes=list(links['concept_tag'].unique())

# Initialize a HeteroData object
data = HeteroData(
    materials={'x': materials}, concepts={'x': concepts})


edge_index, edge_label = load_edge_csv(
    links_path,
    src_index_col='material_tag',
    src_mapping=materials_mapping,
    dst_index_col='incremental_concept_tag',
    dst_mapping=concepts_mapping,
)

data['materials', 'links', 'concepts'].edge_index = edge_index
data['materials', 'links', 'concepts'].edge_label = edge_label

print(data)
pickle.dump(data, open('../data/datav3.pkl', 'wb'))
