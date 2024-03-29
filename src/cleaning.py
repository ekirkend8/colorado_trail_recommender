import os
import pandas as pd
import numpy as np 
import matplotlib.pyplot as plt
import json, string, random
from pymongo import MongoClient
from pathlib import Path
import pickle
from src.nlp_pipeline import *
from sklearn.decomposition import NMF, PCA
from src.stopwords_class import StopWords
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler
from src.configs.get_configs import get_all_configs
from src.data_connections.dbs import get_mongo_data


def mongo_to_dataframe(mongo_db):
    """ Fetch data from MongoDB and store as JSON. """
    data = pd.DataFrame(list(mongo_db.find()))

    return data


def clean_df(raw_df):
    '''
    Raw json dataframe cleaned and returned.

    Input: Pandas dataframe
    Output: Pandas dataframe
    '''
    raw_df.drop('_id', axis=1,inplace=True)
    raw_df = raw_df.drop_duplicates(subset='url')
    raw_df.set_index('name', inplace=True)
    raw_df.index = raw_df.index.where(~raw_df.index.duplicated(), raw_df.index + '_2')
    raw_df.index = raw_df.index.where(~raw_df.index.duplicated(), raw_df.index + '_3')
    raw_df.index = raw_df.index.where(~raw_df.index.duplicated(), raw_df.index + '_4')

    return raw_df


def get_review_corpus(data):
    '''
    Create dataframe containing concatenated reviews.

    Input: Pandas series.
    Output: List of hike names, list of strings
    '''
    rows = []
    docs = []
    for i in range(len(data)):
        row_name = data.index[i]
        document = ''
        if data[i] is not None:
            for k, v in data[i].items():
                if type(v) == list:
                    document += (v[2].strip().replace('\n', ' ').replace('\r', ' ') + ' ')
            docs.append(document)
            rows.append(row_name)
        else:
            docs.append(document)
            rows.append(row_name)
    return rows, docs


def make_reviews_df(index, documents, col_names=['reviews']):
    '''
    Make review dataframe from hike reviews text.

    Input: Index list, documents list, column names.
    Output: Pandas dataframe
    '''
    return pd.DataFrame(documents, index=index, columns=col_names)


def make_corpus_df(raw_df, review_df):
    '''
    Make main corpus dataframe of documents including: tags, main description, secondary description and reviews.

    Input: Pandas dataframes.
    Output: Pandas dataframe.
    '''
    df_corpus = pd.DataFrame(raw_df[['url', 'tags', 'main_description', 'secondary_description']])
    df_corpus['review_string'] = review_df['reviews']
    df_corpus.fillna('', inplace=True)
    df_corpus['all'] = df_corpus['tags'] + ' ' + df_corpus['main_description'] + ' ' + df_corpus['secondary_description'] + ' ' + df_corpus['review_string']
    return df_corpus


def make_hike_df(raw_df):
    '''
    Make main hike dataframe containing: url, location, difficulty, elevation, distance, average rating, number of ratings.

    Input: Pandas dataframe.
    Output: Pandas dataframe.
    '''
    df_hike = raw_df.copy()
    df_hike.drop(['tags', 'main_description', 'secondary_description', 'reviews'], axis=1, inplace=True)
    return df_hike


def get_top_words_tf(X, features, n_words=10):
    '''
    Get top n words from term-frequency matrix.

    Input: X matrix, words, int
    Output: Dictionary of top words and frequency
    '''
    summed = np.sum(X, axis=0)
    summed = np.array(summed).reshape(-1,) 
    indices_top = np.argsort(-summed)[:n_words]
    top_dict = {str(features[i]): int(summed[i]) for i in indices_top}
    return top_dict


def nmf_topic_modeling(corpus, tfidf_matrix, tfidf_feats, n_topics, n_words=10, max_iter=250, print_tab=False):
    '''
    Perform NMF, get top n words for each topic, make dataframe for both W and H matrices.

    Input: Pandas dataframe, TFIDF matrix, TFIDF features, number of topics desired, number of top words desired, max iterations, print tabulate.
    Output: Pandas dataframe of topics and top words, pandas dataframes
    '''
    ## NMF
    W, H = get_nmf(tfidf_matrix, n_components=n_topics, max_iter=max_iter)
    top_words = get_topic_words(H, tfidf_feats, n_words)
    df_pretty = print_topics(top_words, False)
    ## Add majority topic to hikes
    copy_maincorpus = corpus.copy()
    copy_maincorpus['topics'] = document_topics(W)
    ## Make df with loadings
    cols = ['topic_'+str(i) for i in range(1,n_topics+1)]
    W_df = pd.DataFrame(W.round(2), index=copy_maincorpus.index, columns=cols)
    W_df['majority_topic'] = document_topics(W)
    W_df['majority_topic'] += 1
    H_df = pd.DataFrame(H.round(2), index=cols, columns=tfidf_feats)
    return df_pretty, W_df, H_df

def hike_url_dict(raw_df):
    '''Make dictionary of hikes and their corresponding URLs.'''
    return {raw_df.index[i]: raw_df['url'][i] for i in range(len(raw_df))}   

def make_sim_matrix(merged_df, similarity_measure=cosine_similarity, mean=True, std=True):
    '''
    Normalize columns, create similarity matrix.
    
    Input: Pandas dataframe, similarity metric, boolean
    Output: Pandas dataframes, numpy matrix
    '''
    ss = StandardScaler(with_mean=mean, with_std=std)
    df_scaled = pd.DataFrame(ss.fit_transform(merged_df), columns=merged_df.columns, index=merged_df.index) 
    X = df_scaled.values
    similarity_df = pd.DataFrame(cosine_similarity(X, X), index=df_scaled.index, columns=df_scaled.index)
    return df_scaled, similarity_df, X

def get_hike_recommendations(baseline_hike, n_hikes):
    '''Generate recommendations given a baseline hike and the number of desired hikes to return.'''
    sim_series = similarity_df.loc[baseline_hike]
    idx = np.argsort(sim_series)[::-1][1:n_hikes+1]
    hikes = df_merged.index
    recs = [hikes[i] for i in idx]
    print(f"Because you enjoyed {baseline_hike}, you may like these:\n")
    for i, rec in zip(idx, recs):
        print(f"{hikes[i]}: {hike_url_dict[rec]}")

def _get_user_profile(items):
    '''
    Takes a list of items and returns a user profile. A vector representing the likes of the user.

    Input: List, list of hike names user likes / has done
    Output: Numpy array, array representing the likes of the user 
    '''
    user_profile = np.zeros(X.shape[1])
    for i in items:
        idx = np.where(hikes==i)[0][0]
        user_profile += X[idx]
    return user_profile

def get_user_recommendation(items, n=5):
    '''
    Takes a list of hikes user liked and returns the top n items for that user

    Input: List, list of trail names user likes/has done; int, number of items to return
    Output: None
    '''
    user_prof = _get_user_profile(items)
    user_similarity = cosine_similarity(X, user_prof.reshape(1, -1))
    idx = np.argsort(user_similarity[:,0])[::-1][len(items):n+len(items)]
    recs = [hikes[i] for i in idx]
    print(f"Because you enjoyed {', '.join(items)}, you may like these:\n")
    for i, rec in zip(idx, recs):
        print(f"{hikes[i]}: {hike_url_dict[rec]}")

def import_csv(filepath, idx_name='Unnamed: 0'):
    '''
    Import csv and tidy up index.
    '''
    df = pd.read_csv(filepath)
    df.set_index(idx_name, inplace=True)
    df.rename_axis(None, inplace=True)
    return df


def save_to_pickle(path, data):
    """
    """
    with open(path, 'wb') as f:
        pickle.dump(data, f)


if __name__ == "__main__":
random.seed(9)
import_ = False
rerun = True
config_file = "src/configs/config.ini"
pickle_path = Path("data/model_data.pickle")
configs = get_all_configs(config_file)
mongo_configs = configs["mongo"]

if os.path.exists(pickle_path):
    data_dict = pickle.load(pickle_path)
else:
client, colorado_hikes = get_mongo_data(mongo_configs)

df_mongo = mongo_to_dataframe(colorado_hikes)
df_clean = clean_df(df_mongo)
hike_url_dict = hike_url_dict(df_mongo)
rows, docs = get_review_corpus(df_mongo['reviews'])
df_reviews = make_reviews_df(rows, docs)
df_corpus = make_corpus_df(df_mongo, df_reviews)
df_hike = make_hike_df(df_mongo)

punc = string.punctuation
stop = StopWords()
stop_words = stop.all_words
clean_column(df_corpus, 'all', punc)
X_tfidf, feats_tfidf, tfidf_vect = vectorize(df_corpus, 'all', stop_words, 6000)
df_trunc = pd.DataFrame(df_corpus['all'])
df_pretty, W_df, H_df = nmf_topic_modeling(df_trunc, X_tfidf, feats_tfidf, n_topics=8, n_words=10)

df_merged = df_hike.merge(W_df, left_index=True, right_index=True).drop(['url', 'majority_topic', 'location', 'number_ratings'], axis=1)
cols_dummy = ['difficulty', 'hike_type']
df_merged = pd.get_dummies(df_merged, columns=cols_dummy, drop_first=True)
cols_to_rename = {'hike_type_Out & Back':'out_and_back', 'hike_type_Point to Point':'point_to_point'}
df_merged = df_merged.rename(columns=cols_to_rename)

df_scaled, similarity_df, X = make_sim_matrix(df_merged)

sim_series = similarity_df.loc['Royal Arch Trail']
idx = np.argsort(sim_series)[::-1][1:11]
hikes = df_merged.index
for i in idx:
    print(hikes[i])

data_dict = dict(
    df_mongo=df_mongo,
    df_corpus=df_corpus,
    df_hike=df_hike,
    df_merged=df_merged,
)

save_to_pickle(pickle_path, data_dict)


    if import_:
        df_mongo = import_csv('../data/raw_hiking_data.csv')
        df_corpus = import_csv('../data/corpus_data.csv')
        df_hike = import_csv('../data/hike_data.csv')
        df_merged = import_csv('../data/topics_and_numericalfeatures.csv')
        df_dogs_allowed = import_csv('../data/dogs_allowed.csv')
        df_dogs_with_topics = import_csv('../data/dogs_with_topics.csv')
        df_pretty = import_csv('../data/prettiedtopics.csv')
        print(df_merged.head())

        df_merged[['out_and_back', 'point_to_point']] = df_merged[['out_and_back', 'point_to_point']]*.1
        df_merged[['difficulty_hard', 'difficulty_moderate']] = df_merged[['difficulty_hard', 'difficulty_moderate']]*.5

        df_scaled, similarity_df, X = make_sim_matrix(df_merged)
        all_hikes = df_mongo.index
        hike_url_dict = hike_url_dict(df_mongo)

        no_dogs_hike_names = df_mongo[df_mongo['tags'].str.contains('no dogs')].index