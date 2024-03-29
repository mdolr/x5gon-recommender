import csv
import json
import requests
import wikipediaapi
from tqdm import tqdm
from slugify import slugify

from urllib.parse import urlparse
from urllib.parse import parse_qs


wiki = wikipediaapi.Wikipedia('en')
BASE_URL = 'https://platform.x5gon.org/api/v1/'

links_file_path = '../data/links.csv'
concepts_file_path = '../data/concepts.csv'
materials_file_path = '../data/materials.csv'
stored_concepts_json_path = '../data/concepts.json'

concept_tag = 0
material_tag = 0


def get_materials(url=None, limit=20, offset=0, debug=False):
    """
    Get OER materials from the API
    """

    # So we can pass a next page URL without having to rebuild it
    if url is None:
        url = BASE_URL + f'/oer_materials?limit={limit}&offset={offset}'

    if debug:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        print(
            f'Getting materials from ID {query_params["offset"][0]} to {int(query_params["offset"][0]) + int(query_params["limit"][0])}...')

    # Get the data and return the JSON
    response = requests.get(url)
    return response.json()


def get_material_content(id):
    """
    Get a single OER material from the API
    """

    url = BASE_URL + f'/oer_materials/{id}/value'

    # Get the data and return the JSON
    response = requests.get(url)
    return response.json()


def get_concept(page_title):
    """
    Get a Wikipedia concept from the API
    """
    page = wiki.page(page_title)

    return {
        'title': page.title,
        'description': page.summary.replace(
            '\r\n', ' ').replace(
            '\n\r', ' ').replace('\n', ' ').replace('\r', ' ').replace(',', ' '),
        'text': page.text.replace(
            '\r\n', ' ').replace(
            '\n\r', ' ').replace('\n', ' ').replace('\r', ' ').replace(',', ' '),
        'page_length': len(page.text)
    }


def crawl(next_page_url=None, first=True):
    """
    Construct the dataset
    """

    if next_page_url is not None or (next_page_url is None and first):
        # Get the list of materials
        materials = get_materials(url=next_page_url, debug=True)
        data = materials['oer_materials']

        # Then from the response, get the next page URL
        # if it exists
        if materials['links']['next']:
            next_page_url = materials['links']['next']

        # For each material in the data list
        for material in tqdm(data, leave=False):
            if (material['description'] is not(None) and len(material['description']) > 50) and material['language'] == 'en':
                global material_tag
                material['tag'] = material_tag

                for concept in tqdm(material['wikipedia'], leave=False):
                    if concept['secName']:
                        global concept_tag
                        concept['tag'] = concept_tag
                        # Get the concept from wikipedia
                        # to get data as the page length
                        concept['slug'] = slugify(concept['secName'])

                        if concept['slug'] in stored_concepts:
                            links_writer.writerow(
                                {'concept_slug': concept['slug'], 'material_id': material['material_id'], 'target': concept['pageRank'], 'material_tag': material_tag, 'concept_tag': concept_tag})

                        else:
                            wikipedia_data = get_concept(concept['secName'])
                            concept.update(wikipedia_data)

                            if concept['text'] is not None and len(concept['text']) > 50:
                                stored_concepts.append(concept['slug'])
                                stored_concepts_json_file.seek(0)
                                json.dump(stored_concepts,
                                          stored_concepts_json_file)

                                links_writer.writerow(
                                    {'concept_slug': concept['slug'], 'material_id': material['material_id'], 'target': concept['pageRank'], 'material_tag': material_tag, 'concept_tag': concept_tag})

                                concept.pop('pageRank')

                                concepts_writer.writerow(concept)
                                concept_tag += 1

                material.pop('wikipedia')
                material.pop('content_ids')
                material.pop('metadata')

                material['provider_id'] = material['provider']['provider_id']
                material['provider_name'] = material['provider']['provider_name']
                material['provider_domain'] = material['provider']['provider_domain']
                material.pop('provider')

                if material['description']:
                    material['description'] = material['description'].replace(
                        '\r\n', ' ')
                    material['description'] = material['description'].replace(
                        '\n\r', ' ')
                    material['description'] = material['description'].replace(
                        '\n', ' ').replace('\r', '')
                else:
                    material['description'] = ''

                materials_writer.writerow(material)
                material_tag += 1
            else:
                continue

        # Once we're done with all the materials
        # Crawl next page
        crawl(next_page_url=next_page_url, first=False)


with open(links_file_path, 'w', newline='') as links_file:
    with open(concepts_file_path, 'w', newline='') as concepts_file:
        with open(materials_file_path, 'w', newline='') as materials_file:
            with open(stored_concepts_json_path, 'w', newline='') as stored_concepts_json_file:

                stored_concepts = []  # json.load(stored_concepts_json_file)

                links_writer = csv.DictWriter(
                    links_file, fieldnames=['material_tag', 'concept_tag', 'concept_slug', 'material_id', 'target'])
                concepts_writer = csv.DictWriter(
                    concepts_file, fieldnames=['tag', 'slug', 'title', 'description', 'text', 'page_length',  'uri', 'name', 'secUri', 'secName', 'lang', 'supportLen'])
                materials_writer = csv.DictWriter(
                    materials_file, fieldnames=['tag', 'material_id', 'title', 'description', 'url', 'language', 'creation_date', 'retrieved_date', 'type', 'extension', 'mimetype', 'provider_id', 'provider_name', 'provider_domain', 'license'])

                links_writer.writeheader()
                concepts_writer.writeheader()
                materials_writer.writeheader()

                crawl()
