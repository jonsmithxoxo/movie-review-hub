import joblib
import random
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score

BASE_DATA = [
    ("Amazing movie I loved it", 9),
    ("Great acting and story", 8),
    ("Masterpiece brilliant film", 10),
    ("Outstanding direction and acting", 9),
    ("Very good enjoyable movie", 8),
    ("Loved every minute of it", 9),
    ("It was okay not great", 6),
    ("Average movie slow in parts", 5),
    ("Decent but could be better", 6),
    ("One time watch", 5),
    ("Bad movie boring plot", 3),
    ("Terrible waste of time", 2),
    ("Worst movie ever", 1),
    ("I hate this film", 2),
    ("Poor acting and bad script", 3)
]               

POS = [
    "absolutely loved it","fantastic","brilliant","highly recommended",
    "great storytelling","amazing visuals","emotionally powerful"
]
NEU = [
    "it was fine","not bad","average experience","okayish","could be better"
]
NEG = [
    "boring","waste of money","poor execution","terrible acting",
    "disappointing","not recommended"
]

def augment(data):
    out=[]
    for t,r in data:
        out.append((t,r))
        if r>=8:
            for p in random.sample(POS,2):
                out.append((t+" "+p,min(10,r+1)))
        elif r>=5:
            for p in random.sample(NEU,2):
                out.append((t+" "+p,r))
        else:
            for p in random.sample(NEG,2):
                out.append((t+" "+p,max(1,r-1)))
    return out

dataset=augment(BASE_DATA)
texts=[x[0] for x in dataset]
ratings=np.array([x[1] for x in dataset])

vectorizer=TfidfVectorizer(
    stop_words="english",
    ngram_range=(1,2),
    max_features=6000
)

X=vectorizer.fit_transform(texts)
Xtr,Xte,Ytr,Yte=train_test_split(X,ratings,test_size=0.25,random_state=42)

model=LinearRegression()
model.fit(Xtr,Ytr)

pred=model.predict(Xte)
pred=np.clip(pred,1,10)

joblib.dump(model,"rating_model.pkl")
joblib.dump(vectorizer,"vectorizer.pkl")
joblib.dump({
    "samples":len(dataset),
    "features":X.shape[1],
    "mse":round(mean_squared_error(Yte,pred),3),
    "r2":round(r2_score(Yte,pred),3)
},"model_metadata.pkl")

print("✅ AI model trained successfully")
