import subprocess
import sys
import os
from numpy import zeros
from numpy.linalg import norm
from collections import Counter
from collections import deque
from pca import pca_svd
from scipy.sparse import csc_matrix 

_quiet_ = False
_buffer_ = '<*>'
_rare_ = '<?>'

def set_quiet(quiet):
    global _quiet_
    _quiet_ = quiet

def count_ngrams(corpus, n_vals=False):
    assert(os.path.isfile(corpus))    
    if n_vals == False:
        answer = raw_input('Type in the values of n (e.g., \"1 3\"): ')        
        n_vals = [int(n) for n in answer.split()]
    
    num_tok = 0
    ngrams = [Counter() for n in n_vals]                                      
    queues = [deque([_buffer_ for _ in range(n-1)], n) for n in n_vals]
    with open(corpus) as f:
        while True:
            lines = f.readlines(10000000) # caching lines
            if not lines:
                break
            for line in lines:
                toks = line.split()
                for tok in toks:
                    num_tok += 1
                    if num_tok % 1000 is 0:
                        inline_print('Processed %i tokens' % (num_tok))
                    for i in range(len(n_vals)):
                        queues[i].append(tok)
                        ngrams[i][tuple(queues[i])] += 1
                 
    for i in range(len(n_vals)):
        for _ in range(n_vals[i]-1):
            queues[i].append(_buffer_)
            ngrams[i][tuple(queues[i])] += 1

    say('\nTotal {} tokens'.format(num_tok))
    files = [os.path.dirname(corpus)+'/'+os.path.splitext(os.path.basename(corpus))[0]+'.'+str(n)+'grams' for n in n_vals]        
    for i in range(len(n_vals)):
        say('Sorting {} {}grams and writing to: {}'.format(len(ngrams[i]), n_vals[i], files[i]))
        sorted_ngrams = sorted(ngrams[i].items(), key=lambda x: x[1], reverse=True)
        with open(files[i], 'wb') as outf:
            for ngram, count in sorted_ngrams:
                for tok in ngram:
                    print >> outf, tok,
                print >> outf, count

def cutoff_rare(ngrams, cutoff, unigrams, given_myvocab):
    assert(unigrams and os.path.isfile(unigrams)) 
    outfname = ngrams + '.cutoff' + str(cutoff) 
    
    if(given_myvocab):
        myvocab = scrape_words(given_myvocab)
        myvocab_hit = {}
        outfname += '.' + os.path.splitext(os.path.basename(given_myvocab))[0]
    
    say('Reading unigrams')
    vocab = {}
    num_unigrams = 0 
    with open(unigrams) as f:
        for line in f:
            num_unigrams += 1
            toks = line.split()
            if len(toks) != 2:
                continue
            word = toks[0]
            count = int(toks[1])
            
            if count > cutoff:
                vocab[word] = count

            if given_myvocab and word in myvocab:
                vocab[word] = count
                myvocab_hit[word] = True
    
    say('Will keep {} out of {} words'.format(len(vocab), num_unigrams))
    if given_myvocab:
        say('\t- They include {} out of {} in my vocab'.format(len(myvocab_hit), len(myvocab)))

    vocab['_START_'] = True # for google n-grams 
    vocab['_END_'] = True    
    
    ans = raw_input('Do you want to proceed with the setting? [Y/N] ')
    if ans == 'N' or ans == 'n':
        exit(0)

    new_ngrams = Counter()    
    n = 0
    num_lines = count_file_lines(ngrams)
    linenum = 0
    with open(ngrams) as f:
        for line in f:
            linenum += 1
            toks = line.split()
            ngram = toks[:-1]
            n = len(ngram)
            count = int(toks[-1])
            new_ngram = []
            for gram in ngram:
                this_tok = gram if gram in vocab else _rare_
                new_ngram.append(this_tok)
            new_ngrams[tuple(new_ngram)] += count
            if linenum % 1000 is 0:
                inline_print('Processing line %i of %i' % (linenum, num_lines))
        
    say('\nSorting {} {}grams and writing to: {}'.format(len(new_ngrams), n, outfname))
    sorted_ngrams = sorted(new_ngrams.items(), key=lambda x: x[1], reverse=True)
    with open(outfname, 'wb') as outf:
        for ngram, count in sorted_ngrams:
            for gram in ngram:
                print >> outf, gram,
            print >> outf, count

def phi(token, rel_position):
    if rel_position > 0:
        position_marker = '<+'+str(rel_position)+'>'
    elif rel_position < 0:
        position_marker = '<'+str(rel_position)+'>'
    else:
        position_marker = ''
    feat = token+position_marker
    holder = {feat : True}
    return holder

def extract_views(ngrams):
    outfname = ngrams + '.featurized'
    say('Writing the featurized file to: ' + outfname)
    
    num_lines = count_file_lines(ngrams)
    linenum = 0    
    with open(outfname, 'wb') as outf:
        with open(ngrams) as f:
            for line in f:
                linenum += 1
                toks = line.split()
                ngram = toks[:-1]
                count = int(toks[-1])
                center = len(ngram) / 2 # position of the current word
                print >> outf, count,

                view1_holder = phi(ngram[center], 0)
                for view1f in view1_holder:
                    print >> outf, view1f,
                    
                print >> outf, '|:|',
                
                for i in range(len(ngram)): 
                    if i != center:
                        view2_holder = phi(ngram[i], i-center)
                        for view2f in view2_holder:
                            print >> outf, view2f,
                print >> outf
                if linenum % 1000 is 0:
                    inline_print('Processing line %i of %i' % (linenum, num_lines))
    inline_print('\n')

def spelling_phi(tok):
    holder = {}
    holder['p1='+tok[0]] = True
    holder['s1='+tok[-1]] = True
    if len(tok) > 1:
        holder['p2='+tok[:2]] = True
        holder['s2='+tok[-2:]] = True
    if len(tok) > 2:
        holder['p3='+tok[:3]] = True
        holder['s3='+tok[-3:]] = True
    if len(tok) > 3:
        holder['p4='+tok[:4]] = True
        holder['s4='+tok[-4:]] = True
    return holder

def augment_spelling(views, unigrams, cutoff, weight):
    assert(os.path.isfile(views) and os.path.isfile(unigrams) and cutoff and weight)
    say('Reading unigrams')
    spelling_count = Counter()
    with open(unigrams) as f:
        for line in f:
            toks = line.split()
            if len(toks) != 2:
                continue
            word = toks[0]
            count = int(toks[1])
            holder = spelling_phi(word)
            for feat in holder:
                spelling_count[feat] += count
                
    sorted_spelling_feats = sorted(spelling_count.items(), key=lambda x: x[1], reverse=True)
    spelling_vocab = {}
    for feat, _ in sorted_spelling_feats[:cutoff]:
        spelling_vocab[feat] = True
    
    say('Augment views {} with spelling features: using weight {}'.format(views, weight))
    num_lines = count_file_lines(views)
    linenum = 0
    with open(views+'.spelling', 'wb') as outf:
        with open(views) as f:
            for line in f:
                linenum += 1
                toks = line.split()
                curtain = toks.index('|:|')
                
                print >> outf, toks[0], # count
                # view 1 features
                for i in range(1, curtain):
                    print >> outf, toks[i], # token itself
                    holder = spelling_phi(toks[i])
                    for feat in holder:
                        if feat in spelling_vocab:
                            print >> outf, feat + '<val>' + str(weight),
                
                print >> outf, '|:|',
                
                # view 2 features
                for i in range(curtain+1, len(toks)):
                    print >> outf, toks[i], # token itself
                    holder = spelling_phi(toks[i][:-4])
                    for feat in holder:
                        if feat in spelling_vocab:
                            print >> outf, feat + toks[i][-4:] + '<val>' + str(weight),
                print >> outf
                if linenum % 1000 is 0:
                    inline_print('Processing line %i of %i' % (linenum, num_lines))
        inline_print('\n')

def update_mapping(raw_feat_tok, smap, imap, featval, head):
    feat_obj = raw_feat_tok.split('<val>')
    featstr = feat_obj[0]
    if not featstr in smap:
        smap[featstr] = head
        imap[head] = featstr
        featval[head] = 1 if len(feat_obj) == 1 else float(feat_obj[1]) 
        head += 1
    return smap[featstr], head    
    
def compute_invsqrt_diag_cov(sqmass, kappa, M):
    smoothed_variances = (sqmass + kappa) / M 
    diags = [i for i in range(len(sqmass))]
    invsqrt_cov = csc_matrix((pow(smoothed_variances, -.5), (diags, diags)), shape=(len(sqmass), len(sqmass)))     
    return invsqrt_cov

def inline_print(string):
    sys.stderr.write("\r\t%s" % (string))
    sys.stderr.flush()

def count_file_lines(fname):
    p = subprocess.Popen(['wc', '-l', fname], stdout=subprocess.PIPE, 
                                              stderr=subprocess.PIPE)
    result, err = p.communicate()
    if p.returncode != 0:
        raise IOError(err)
    return int(result.strip().split()[0])

def say(string, newline=True):
    if not _quiet_:        
        if newline:
            print string
            sys.stdout.flush()
        else:
            print string,
            sys.stdout.flush()

def perform_pca(embedding_file, pca_dim, top):
    freqs, words, A, _, _ = read_embeddings(embedding_file)
    say('performing PCA to reduce dimensions from {} to {}'.format(A.shape[1], pca_dim))            
    pca_trans, _, _ = pca_svd(A) 
    A_pca = pca_trans[:,:pca_dim]
    write_embeddings(freqs, words, A_pca, embedding_file + '.pca' + str(pca_dim))

def read_embeddings(embedding_file):
    freqs = {}
    words = {}
    w2i = {}
    rep = {}
    
    say('reading {}'.format(embedding_file))
    
    with open(embedding_file) as f:
        for i, line in enumerate(f):    
            toks = line.split()
            freqs[i] = toks[0]
            words[i] = toks[1]
            w2i[toks[1]] = i
            rep[toks[1]] = map(lambda x: float(x), toks[2:])
    
    say('total {} embeddings of dimension {}'.format(len(rep), len(rep[rep.keys()[0]])))            

    A = zeros((len(rep), len(rep[rep.keys()[0]])))
    for i in range(len(rep)):
        A[i,:] = rep[words[i]]
  
    return freqs, words, A, w2i, rep

def write_embeddings(freqs, words, matrix, filename):
    with open(filename, 'wb') as outf:
        for i in range(len(words)):
            print >> outf, freqs[i], words[i],
            for val in matrix[i,:]:
                print >> outf, val,
            print >> outf
    
def normalize_rows(embedding_file):
    freqs, words, A, _, _ = read_embeddings(embedding_file)    
    say('normalizing rows')
    for i in range(A.shape[0]):
        A[i,:] /= norm(A[i,:])
    write_embeddings(freqs, words, A, embedding_file + '.rows_normalized')
    
def command(command_str):
    say(command_str)
    os.system(command_str)

def scrape_words(given_myvocab): 
    myvocab = {}
    with open(given_myvocab) as f:
        for line in f:
            toks = line.split()
            if len(toks) == 0:
                continue
            myvocab[toks[0]] = True
    return myvocab



