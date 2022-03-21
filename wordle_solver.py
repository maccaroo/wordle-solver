#####################
### Wordle Solver ###
#####################

import pandas as pd
import string
import time
from datetime import date
import json

import selenium
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC

### Vars
word_len = 5
game_uri = "https://www.nytimes.com/games/wordle/index.html"
lexicon_uri = "lexicon.txt" # Include any file containing 1 word per line
log_file = "wordle_solver.log"

### Setup & Start browser

options = ChromeOptions()
#options.headless = True # Uncomment to run without open browser
options.add_argument("--window-size=640,1200")

service=Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)

try:
    driver.get(game_uri)
    elem = WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.CSS_SELECTOR, "game-app")))
except TimeoutException:
    print("Timeout")
    
### Dismiss introductory modal
item = driver.execute_script("""return document
.querySelector('game-app').shadowRoot
.querySelector('game-theme-manager')
.querySelector('game-modal').shadowRoot
.querySelector('game-icon')
""")
item.click()

### Information
def create_information_store():
    """
    Create object to store learned information.
    """
    return {
        "pos_known_pos": list(),
        "pos_known_neg": list(),
        "is_present": list(),
        "eliminated": list()
    }

### Get lexicon
df_words = pd.read_csv(lexicon_uri, header=None)
df_words.columns = ["Word"]

# Filter
df_words = df_words[df_words["Word"].str.len() == word_len]
df_words = df_words[df_words["Word"].str.isalpha()]

### Add details

# Break out letters
for pos in range(0, word_len):
    df_words[pos] = df_words["Word"].str[pos]

# Frequency in position
def set_in_pos_score(df):
    """
    Set the in-position score.
    """
    def freq_in_pos_letter_score(pos, letter):
        return freqs[pos].at[letter]
    
    def freq_in_pos_word_score(word):
        return sum([freqs[pos].at[letter] for pos, letter in enumerate(word)])
    
    freqs = [df[pos].value_counts() for pos in range(word_len)]
    df["In Pos Score"] = df["Word"].apply(freq_in_pos_word_score)
    
    for pos in range(0, word_len):
        df[f"{pos}-scr"] = df["Word"].apply(lambda word: freq_in_pos_letter_score(pos, word[pos]))
    
    df.sort_values(by=['In Pos Score'], ascending=False, ignore_index=True, inplace=True)

def is_unique_letters(word):
    """
    Return whether the word has only unique letters.
    """
    if len(word) == 1:
        return True
    first = word[0]
    for pos in range(1, len(word)):
        if first == word[pos]:
            return False
    return is_unique_letters(word[1:])


def unique_letters_only(df):
    """
    Get the values from the dataframe which have unique letters only.
    """
    df_uniq = df.copy()[df["Word"].apply(is_unique_letters)]
    return df_uniq

def add_letter(letter):
    """
    Add the letter to the current word.
    """
    item = driver.execute_script(f"""return document
    .querySelector('game-app').shadowRoot
    .querySelector('game-theme-manager')
    .querySelector('game-keyboard').shadowRoot
    .querySelector('#keyboard button[data-key="{letter}"]')
    """)
    item.click()
    
def game_toaster_error():
    """
    Check whether the toaster has an error.
    """
    item = driver.execute_script("""return document
    .querySelector('game-app').shadowRoot
    .querySelector('game-theme-manager')
    .querySelector('div#game-toaster')
    """)
    return item.text if item else None
    
def submit_word():
    """
    Submit the entered word.
    """
    item = driver.execute_script("""return document
    .querySelector('game-app').shadowRoot
    .querySelector('game-theme-manager')
    .querySelector('game-keyboard').shadowRoot
    .querySelector('#keyboard button[data-key="↵"]')
    """)
    item.click()
    error = game_toaster_error()
    if error == "Not in word list":
        return False
    return True

def read_guess_letter(row, ordinal):
    """
    Read the specified letter's result.
    """
    item = driver.execute_script(f"""return document
    .querySelector('game-app').shadowRoot
    .querySelector('game-theme-manager')
    .querySelectorAll('game-row')['{row}'].shadowRoot
    .querySelectorAll('game-tile')['{ordinal}']
    """)
    return item.get_attribute("evaluation")
    
def read_guess_word(row):
    """
    Read the specified row's results.
    """
    guess_result = [read_guess_letter(row, ordinal) for ordinal in range(word_len)]
    return guess_result

mapping = {"absent": "B", "present": "Y", "correct": "G"}

def map_guess(results):
    """
    Map the returned letter values to the expected values.
    """
    return [mapping[raw] for raw in results]
    
def try_word_online(attempt, word):
    """
    Enter the letters for this word and submit.
    """
    [add_letter(letter) for letter in word]
    submit_word()
    guess_result = read_guess_word(attempt-1)
    if guess_result[0] is not None:
        return map_guess(read_guess_word(attempt-1))
    return "XXXXX" # Placeholder to invalid guess

def clear_guess():
    """
    Remove the letters from any previous guess.
    """
    item = driver.execute_script("""return document
    .querySelector('game-app').shadowRoot
    .querySelector('game-theme-manager')
    .querySelector('game-keyboard').shadowRoot
    .querySelector('#keyboard button[data-key="←"]')
    """)
    [item.click() for _ in range(word_len)]
    
def has_letter(tuple_list, letter):
    for (pos, tuple_letter) in tuple_list:
        if letter == tuple_letter:
            return True
    return False

def learn(word, guess_result, information_store):
    """
    Learn new information from the word and guess result.
    """
    for pos, letter in enumerate(word):
        pos_result = guess_result[pos]
        if pos_result == 'B':
            if not has_letter(information_store["pos_known_pos"], letter) and letter not in information_store["eliminated"]: 
                information_store["eliminated"].append(letter)
            elif has_letter(information_store["pos_known_pos"], letter) and not has_letter(information_store["pos_known_neg"], letter):
                information_store["pos_known_neg"].append((pos,letter))
            continue
        if pos_result == 'Y':
            if letter not in information_store["is_present"]: information_store["is_present"].append(letter)
            if not (pos,letter) in information_store["pos_known_neg"]: information_store["pos_known_neg"].append((pos,letter))
            continue
        if pos_result == 'G' and (pos, letter) not in information_store["pos_known_pos"]: 
            information_store["pos_known_pos"].append((pos,letter))
            continue

def prune(df, information_store):
    """
    Prune the available words based on known information.
    """
    for letter in information_store["is_present"]:
        df = df[df["Word"].str.contains(letter)]
    for letter in information_store["eliminated"]:
        df = df[~df["Word"].str.contains(letter)]
    for pos, letter in information_store["pos_known_pos"]:
        df = df[df[pos] == letter]
    for pos, letter in information_store["pos_known_neg"]:
        df = df[df[pos] != letter]
    return df

def prune_word(df, word):
    """
    Prune this word from the available words.
    """
    print(f"Pruning: {word}")
    df = df[df["Word"] != word]
    
    return df
    
def log_guess_record(guess_record):
    """
    Log today's guess record to a file
    """
    with open(log_file, "a") as myfile:
        date_str = date.today().strftime("%y/%m/%d")
        guess_log = {
            "date": date_str,
            "guess record": guess_record
        }
        myfile.write("\n")
        json.dump(guess_log, myfile)
        

def solver(df_all_words, uniq_threshold=1000):
    """
    Run until word solved.
    """
    df_avail = df_all_words.copy()
    info = create_information_store()
    count = 1
    guess_record = []
    while True:
        time.sleep(2) # Allow for page effects, such as when guess is not in word list
        df_uniq = unique_letters_only(df_avail)
        df_x = unique_letters_only(df_avail) if df_uniq.shape[0] > uniq_threshold else df_avail
        set_in_pos_score(df_x)
        df_x.reset_index(drop=True)
        
        guess = df_x.iloc[0]["Word"]
        print(f"Guess {count}: {guess} ({df_x.shape[0]} words)")
        guess_result = try_word_online(count, guess)
        guess_record.append({
            "guess": guess,
            "options": df_x.shape[0],
            "result": "".join(guess_result)
        })
        
        if guess_result == "XXXXX":
            df_avail = prune_word(df_avail, guess)
            clear_guess()
            continue
        
        if guess_result == list(word_len*"G"):
            print(f"Solved: {guess}")
            break

        learn(guess, guess_result, info)
        df_avail = prune(df_avail, info)
        count += 1
        if count > 6:
            break
    return guess_record

guess_record = solver(df_words, 10)
log_guess_record(guess_record)
