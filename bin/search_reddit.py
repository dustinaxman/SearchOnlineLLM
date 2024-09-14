import requests
from bs4 import BeautifulSoup
import time
import sys
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, TimeoutException
from time import sleep
from selenium.webdriver.chrome.service import Service
import random
from rich.console import Console
from rich.markdown import Markdown
import tiktoken 
import anthropic
import argparse
from datetime import datetime


client = anthropic.Anthropic(
    # defaults to os.environ.get("ANTHROPIC_API_KEY")
    api_key=os.environ["ANTHROPIC_API_KEY"],
)

GOOGLE_SEARCH_CSE_ID = os.getenv('GOOGLE_SEARCH_CSE_ID')
GOOGLE_SEARCH_API_KEY = os.getenv('GOOGLE_SEARCH_API_KEY')


# USAGE: python3.9 ~/Downloads/search_reddit.py --search_query "best things to do in the bay area site:reddit.com" --num_links_from_search 15


def parse_args():
    parser = argparse.ArgumentParser(description="Run the Reddit to LLM scraper.")
    parser.add_argument("--search_query", type=str, help="Search query string for Google search.")
    parser.add_argument("--url_list", nargs='+', help="List of URLs to scrape.")
    parser.add_argument("--num_links_from_search", type=int, default=10, help="Number of Google search results to return (default is 10).")
    return parser.parse_args()


def setup_driver():
    # Configure options for Chrome
    options = Options()
    #options.add_argument('--headless')  # Runs Chrome in headless mode.
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(options=options)
    return driver


def get_reddit_post_title_and_body(url):
    """
    This function extracts the title and body of a Reddit post from a given URL.
    Args:
    - url (str): The URL of the Reddit post.
    Returns:
    - tuple: A tuple containing the title and the body of the Reddit post (title, body).
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Check for HTTP errors
        # Parse the page with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        # Extract the title from the 'shreddit-title' tag
        title_tag = soup.find("shreddit-title")
        if title_tag:
            title = title_tag.get("title")
        else:
            title = "Title not found"
        # Extract the body from the div with the post content
        body_tag = soup.find("div", id=lambda x: x and x.endswith("-post-rtjson-content"))
        if body_tag:
            # Extract the paragraphs from the body
            body = "\n".join(p.get_text() for p in body_tag.find_all("p"))
        else:
            body = "Body not found"
        return title, body
    except requests.exceptions.RequestException as e:
        print(f"Error fetching the page: {e}")
        return None, None
    except Exception as e:
        print(f"An error occurred while extracting the post data: {e}")
        return None, None
    sleep(1)



def get_reddit_post_title(url):
    """
    This function extracts the title of a Reddit post from a given URL.
    Args:
    - url (str): The URL of the Reddit post.
    Returns:
    - str: The title of the Reddit post.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Check for HTTP errors
        # Parse the page with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        # Extract the title from the 'shreddit-title' tag
        title_tag = soup.find("shreddit-title")
        if title_tag:
            title = title_tag.get("title")
            return title
        else:
            print("Title tag not found in the page.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching the page: {e}")
        return None
    except Exception as e:
        print(f"An error occurred while extracting the title: {e}")
        return None

def scrape_top_level_comments(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    comments = []
    # Find the div that contains all comments
    for comment_area in soup.find_all("div", class_="_2M2wOqmeoPVvcSsJ6Po9-V"):
        # Each top-level comment is within a div with specific classes
        for comment in comment_area.find_all("div", class_="Comment"):
            # Extract the text from the p tag inside the div
            comment_text = comment.find("p")
            if comment_text:
                comments.append(comment_text.get_text())
    return comments


def google_search_old(query, api_key, cse_id, **kwargs):
    """ Perform a Google search using the Custom Search JSON API. """
    search_url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'q': query,
        'key': api_key,
        'cx': cse_id
    }
    params.update(kwargs)
    response = requests.get(search_url, params=params)
    return response.json()


def google_search(query, api_key, cse_id, num=10):
    """ Perform a Google search using the Custom Search JSON API with pagination support. """
    search_url = "https://www.googleapis.com/customsearch/v1"
    results = []
    start_index = 1
    
    # Google CSE API only allows a maximum of 10 results per request, so we need to loop if num > 10
    while len(results) < num:
        # Calculate how many more results we still need
        batch_size = min(10, num - len(results))  # Fetch up to 10 at a time
        params = {
            'q': query,
            'key': api_key,
            'cx': cse_id,
            'start': start_index,  # For pagination, this is the index of the first result to return
            'num': batch_size
        }
        response = requests.get(search_url, params=params)
        response.raise_for_status()  # Check for HTTP errors
        data = response.json()
        items = data.get('items', [])
        
        # Append new results
        results.extend(items)
        
        # If no more results are available, break out of the loop
        if not items:
            break
        
        # Update the start index for the next batch (Google uses 1-based indexing)
        start_index += batch_size

    return results[:num]  # Return only the number of results requested

def extract_content(url):
    """ Extract and return text and image URLs from the specified URL. """
    try:
        response = requests.get(url)
        response.raise_for_status()  # Check for HTTP errors
        soup = BeautifulSoup(response.text, 'html.parser')
        # Extract text
        text = ' '.join([p.text for p in soup.find_all('p')])
        # Extract image src's
        images = [img['src'] for img in soup.find_all('img') if 'src' in img.attrs]
        return {'url': url, 'text': text, 'images': images}
    except requests.RequestException as e:
        print(f"Failed to retrieve the page: {url}, error: {e}")
        return {'url': url, 'text': '', 'images': []}


def click_load_more_comments(driver):
    # Wait until the load more button is found with the exact class name
    more_replies_buttons = WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "button[class='text-tone-2 text-12 no-underline hover:underline px-xs py-xs flex ml-[3px] xs:ml-0 !bg-transparent !border-0']"))
    )
    for button in more_replies_buttons:
        driver.execute_script("arguments[0].scrollIntoView(true);", button)
        sleep(random.uniform(0.5, 2))  # Ensure the button is visible
        try:
            button.click()  # Attempt to click the button
        except ElementClickInterceptedException:
            # If normal click fails, use JavaScript click
            driver.execute_script("arguments[0].click();", button)
        sleep(random.uniform(1, 2))  # Delay to mimic human interaction and allow for load


def extract_comments(driver, element):
    #sleep(random.uniform(0.5, 2))
    # Extract the main comment text
    # click_load_more_comments(driver, element)
    try:
        comment_text = element.find_element(By.CSS_SELECTOR, "div[slot='comment']").text.strip()
        comment_score = element.get_attribute("score")
    except NoSuchElementException:
        # Handle the case where the comment structure is different or not found
        comment_text = ""
        comment_score = 0
    comment_dict = {
        'text': comment_text,
        'score': comment_score,
        'replies': []
    }
    try:
        # Try to find replies within the same comment block
        replies = element.find_elements(By.CSS_SELECTOR, "shreddit-comment[slot^='children-']")
        for reply in replies:
            # sleep(random.uniform(0.5, 2))
            comment_dict['replies'].append(extract_comments(driver, reply))  # Recursive call for each reply
    except NoSuchElementException:
        print("no replies for this comment")
    return comment_dict


def scrape_reddit_comments(url):
    sleep(random.uniform(0.5, 2))
    driver = setup_driver()
    driver.get(url)
    try:
        while True:
            click_load_more_comments(driver)
    except TimeoutException:
        print("No more 'load more comments' buttons found or timed out waiting for them.")
    except NoSuchElementException:
        print("All comments expanded.")
    except Exception as e:
        print("An error occurred while clicking:", e)
    # Wait for the comments tree to load
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "shreddit-comment-tree"))
        )
    except TimeoutException:
        print("Failed to load the comment tree.")
        driver.quit()
        return []
    sleep(1)  # Ensure all comments have loaded, might need adjustment or scrolling
    comments = []
    root_comment_elements = driver.find_elements(By.CSS_SELECTOR, "shreddit-comment[depth='0']")
    for root_element in root_comment_elements:
        comments.append(extract_comments(driver, root_element))  # Start the recursive extraction
    driver.quit()
    return comments


def format_comments(comments, depth=1, include_replies=True):
    output = ""
    indent = "    " * depth  # Create an indentation based on the depth of the comment
    for comment in comments:
        output += f"{indent}- Comment: {comment['text']}\n"
        output += f"{indent}  Score: {comment['score']}\n"
        if comment['replies'] and include_replies:
            output += f"{indent}  Replies:\n"
            output += format_comments(comment['replies'], depth + 1)  # Recursively format replies
    return output


def calculate_token_count(text):
    encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text, disallowed_special=()))



EXAMPLE_BODY_1 = """
In Short: Does anyone have good recommendation for fantasy series books?

Background:

When I read books, I don't care one bit about character or room descriptions. I just read them vertically. Surely, this must be something a lot of you can relate to. The most important aspect for me is a good plot line.

Also, I'm not sure that this is related to aphantasia, but I have difficulty when there is a lot of multiple names in books. I often have to backtrack or google who a character is when reading.

I really like the "Magician" series from Raymond E. Feist. I never had an issue here with keeping track of names because when a character returns after some time, there is always a little reminder. E.g. "Nakur, the little magician". This triggers the linking in my mind and I know immediately who is meant. There is quite a lot of different names in the books, but it never bothered me because of the way it was handled. I always had troubles with names in books before, but this was the first book I read where this wasn't an issue.

After completing this series, I tried the "Wheel of Time" series from Robert Jordan. I struggled myself through 5 books, but then I let it hang for a while. Picking it up again now would require so much work to know who everyone is again. I always had to google a lot while reading this series, which often spoils some aspects as well.

I didn't know about aphantasia yet while I was reading these books. I've known about it for 2 years now but haven't read since. It all makes a lot more sense now why I struggled so much with the wheel of time. And knowing what I know now, I don't want to pick it up again.

So, do any of you fellow aphants have a good recommendation?
"""

EXAMPLE_BODY_2 = """
Sometime last night I asked about the worst and I'm getting some frankly amazing responses.

But now for my shameless reading list I want to know what you all think is the best.

One of my favorites is Elantris, that book is beautifully written to me and Ive reread it more times than I can count.
"""


EXAMPLE_BODY_3 = """
People CLEARLY need to expand their palette to shows like Breaking Bad or The Sopranos. I want to make it clear that Daredevil can be your favorite show; that’s okay!

Daredevil is a show that had great talent out their hearts into what they had: which wasn’t much. One look at some of the CGI and you know what I mean… it’s good they avoided having to resort to it for most of it.

Daredevil is great in some areas: fight scenes and acting. Cinematography too even if the gear they had wasn’t as quality compared to the standard that recent super hero shows are using.

While the writing was inoffensive, good, and sometimes great, the story still wasn’t anything to applaud whatsoever. It was above average I’d say.

To pretend that the show is in the top 50 TV shows of all time is hilarious to me. And if we’re including movies too… well you seriously need to watch some more stuff besides the action genre.

We need to stop saying that it’s the best superhero live action media to exist. It adapted the source material much better than most of its competitors, but that doesn’t make it better or worse for being comic accurate. The 2017 film “Logan”, was much better than Daredevil, which isn’t anything to scoff at!

While I’m not a big fan of super hero movies or shows to begin with, I have seen the Avengers films (the first two are just okay, the third the best), The Batman, Joker, The Batman, Into The Spider Verse, and TDK trilogy. All of these are better than Daredevil from the standpoint of people who have worked in the film and television industry. A fans perspective while be different from the perspective of an executive producer or editor.

It is a good show, can be great in certain scenes. The season was a solid 8, the second I would give a 6.5, and the third I’d give an 8.5. Nothing more, nothing less. Its good.
"""

EXAMPLE_BODY_4 = """
There have been plenty of great shows since Lost ended 10+ years ago but nothing has come close to it for me.

Lost offered an experience like no other series. All the mysteries and theories (I was satisfied with most of the answers btw), all the crazy twists (like "We have to go back", time travel etc.) and hype..not to mention the best part, the amazing characters who were all so well developed (some of my favourites: Jack, Locke, Sawyer, Juliet).

It wasn't perfect, its clear the writers didn't plan out everything and there is some padding in the earlier seasons + I think the flash side ways in the last season could have been handled better and be less misleading. I love the ending though
"""


def check_if_thread_addresses_query(query, thread_title, thread_body):
    prompt = f"""
    "Given the following query (e.g. google search) assess the following title and body of a reddit thread. 
    Respond with YES if the thread seems directly pertinent to the question and NO otherwise. Below are some examples.  The value in the RESPONSE field is your expected response in these cases.
    EXAMPLE 1: 
        QUERY: "best fantasy novel books", 
        TITLE: "Good fantasy books for aphants? : r/Aphantasia" 
        BODY: {EXAMPLE_BODY_1}
    
    RESPONSE: NO

    this is because although it discusses good fantasy books, it is limited to only those people with aphantasia, which is unlikely to be what the query wants information about specifically.

    EXAMPLE 2: 
        QUERY: "best fantasy novel books", 
        TITLE: "What in your opinion, is the BEST fantasy novel or series that You've read? : r/Fantasy"
        BODY: {EXAMPLE_BODY_2}
    
    RESPONSE: YES

    This is a perfect example of a YES since it aims to address what is the overall best fantasy novel, which seems to be what the user is asking for.

    EXAMPLE 3:
        QUERY: "best tv shows of all time"
        TITLE: "Let’s stop pretending that Daredevil is one of the best TV shows of all time. : r/Daredevil"
        BODY: {EXAMPLE_BODY_3}
    
    RESPONSE: NO

    This is too specific to daredevil. The user asked about best tv shows of all time, this question seems to just dive into one tv show and discuss why it is not as good as others think it is.
    This could be on the fence, if this were a slightly more broad discussion this might become a yes but as it is it is too narrow.
    Reading it wouldn't be very helpful to a user trying to find the "best tv shows of all time".

        EXAMPLE 4:
        QUERY: "best tv shows of all time"
        TITLE: "Anyone else think Lost is still the best tv show of all time? : r/lost"
        BODY: {EXAMPLE_BODY_4}
    
    RESPONSE: NO

    This is too specific to just talking about Lost.  The user seems to be looking for a thread that gets opinions from everyone on their favorite tv show of all time, not just if Lost is their favorite.


    Carefully review these examples and their learnings, then carefully read the following information for a new reddit thread and query and respond either YES or NO.  
    It is absolutely critical that you include no other words in your response other than either "YES" or "NO".

    QUERY: {query}
    TITLE: {thread_title}
    BODY: {thread_body}
    """
    #claude-3-haiku-20240307
    message = client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=1000,
        temperature=0.0,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return message.content[0].text

def reddit_to_llm(search_query=None, url_list=None, num_links_from_search=10):
    reddit_threads_list = []
    if url_list is None:
        url_list = []
    
    # Perform the search
    if search_query is not None:
        print(num_links_from_search)
        results = google_search(search_query, GOOGLE_SEARCH_API_KEY, GOOGLE_SEARCH_CSE_ID, num=num_links_from_search)  # Adjust 'num' as needed
        google_search_urls = [item['link'] for item in results]
    else:
        google_search_urls = []

    print("google_search_urls:")
    for url in google_search_urls:
        print(url)

    print("")
    print("passed_url_list:")
    for url in url_list:
        print(url)
    all_urls = google_search_urls + url_list
    print("")
    print("All urls:")
    print(all_urls)
    print("All reddits selected:")
    for thread_idx, thread_url in enumerate(all_urls):
        if "reddit.com" in thread_url:
            post_title, post_body = get_reddit_post_title_and_body(thread_url)
            good_thread_check = check_if_thread_addresses_query(search_query, post_title, post_body)
            print(thread_url, good_thread_check)
            #print(search_query, post_title, post_body)
            if "YES" in good_thread_check:
                print(thread_url, post_title)
                sleep(random.uniform(1, 2))
                # Example usage
                #thread_url = 'https://www.reddit.com/r/wine/comments/18fn4fg/favorite_bottle_of_wine_under_20/'
                print(thread_url)
                comments = scrape_reddit_comments(thread_url)
                reddit_thread = format_comments(comments)
                reddit_thread_str = f"""
                Reddit thread {thread_idx}:

                {reddit_thread}

                """
                reddit_threads_list.append(reddit_thread_str)

    reddit_threads_str = "".join(reddit_threads_list)

    prompt = f"""
    You will analyze a series of Reddit comments across different threads related to the following query:
    QUERY (google search): {search_query} 
    Your task is to:
    **Rank the query-related elements** mentioned in the comments (e.g., specific items, brands, products) based on the following criteria:
        - **Frequency of mentions**: How often each element is referenced across comments.
        - **Upvotes**: The number of upvotes the comments mentioning each element receive.
        - **Positive replies**: Engagement through supportive replies for each element.
        - **Sentiment**: Whether the overall tone around each element is positive, neutral, or negative, and the degree of each.

    ### Chain of Thought (CoT) Reasoning Process:
    1. **Step 1**: Analyze all query-related elements mentioned and note how frequently they appear.
    2. **Step 2**: Consider the number of upvotes and replies supporting each element.
    3. **Step 3**: Analyze the sentiment (positive, neutral, negative) for each element based on the language used in the comments.
    4. **Step 4**: Based on Steps 1-3, assign a score from 0 to 1, where:
        - **1** indicates that the element is highly regarded and frequently mentioned with positive sentiment and support.
        - **0** indicates that the element is less important or receives little support.

    ### Output Format:
    **Rankings**:
        - Provide a ranked list of the elements along with a score (0-1) for each.
        - The score should reflect the overall user sentiment and support for that element based on the criteria above.
        - Include all elements that are relevant to the query and are mentioned more than 2 times. 
        - No explanation is needed for each ranked element in your response.

    Here is the set of reddit threads:

    {reddit_threads_str}
    """

    return prompt


if __name__=="__main__":
    args = parse_args()
    search_query = args.search_query
    num_links_from_search = args.num_links_from_search
    url_list = args.url_list if args.url_list else []
    if args.cache_prompt:
        with open(args.cache_prompt, 'r') as f:
            prompt = f.read()
    else:
        prompt = reddit_to_llm(search_query=search_query, url_list=url_list, num_links_from_search=num_links_from_search)
        current_datetime = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_name = f"prompt_{current_datetime}.txt"
        home_dir = os.path.expanduser("~")
        file_path = os.path.join(home_dir, "Downloads", file_name)
        with open(file_path, 'w') as f:
            f.write(prompt)


    print(prompt)
    print(calculate_token_count(prompt))
    if calculate_token_count(prompt) > 200000:
        print("OVER LIMIT")

    message = client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=1000,
        temperature=0.0,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    console = Console()
    md = Markdown(message.content[0].text)
    console.print(md)

