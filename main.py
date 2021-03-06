import urllib.request
from urllib.parse import urlparse, urlunparse
import html.parser
import json
import psycopg2
from tumblpy import Tumblpy, TumblpyError
import time

log_file = open("log/main.log", "a")

def cleanup():
  log_file.close()

def log(to_log):
  log_file.write("{0} {1}\n".format(time.ctime(), str(to_log).encode("utf-8")))

def main():
  # Read JSON file to retrieve passwords and API keys
  with open("config.json", "r") as config:
    config_json = json.loads(config.read())

  db = config_json["db"]
  tumblr_api = config_json["tumblr_api"]

  # Load the top posts from /r/all
  front_url = config_json["reddit_url"]
  front_json = try_get_json(front_url, 3)

  # Connect to the database and create a cursor
  conn_string = "dbname={0} user={1} password={2}".format(db["dbname"], \
                                                          db["user"], \
                                                          db["password"])
  cursor = psycopg2.connect(conn_string).cursor()

  # Create a Tumblpy object, used to interact with the Tumblr API.
  tpy = Tumblpy(tumblr_api["consumer-public"],
                tumblr_api["consumer-secret"],
                tumblr_api["oauth-public"],
                tumblr_api["oauth-secret"])
  
  if front_json is not None:
    # Only check the top n posts on the front page.
    for post in front_json["data"]["children"][:config_json["top_n"]]:
      post_data = post["data"]

      if post_is_new(cursor, post_data):
        # post_to_tumblr returns True if it successfully creates a post.
        if post_to_tumblr(tpy, post_data, config_json):
          add_post_to_db(cursor, post_data)


# Try a given number of times to query JSON data from a web page.
def try_get_json(url, times):
  for i in range(1, times):
    try:
      return get_json_from_url(url)
    except Exception as e:
      err_str = "Could not get JSON at '{0}' (attempt {1} of {2})"
      log(err_str.format(url, i, times))
  log("Could not get JSON.")

# Returns the contents of a JSON webpage as a Python object.
def get_json_from_url(url):
  response = urllib.request.urlopen(url)
  contents = response.readall().decode("utf-8")
  return json.loads(contents)

# Returns whether or not a given post is already included in the database.
def post_is_new(cursor, data):
  query = "SELECT * FROM posts where url = %s"
  cursor.execute(query, (data["url"],))
  return cursor.fetchone() is None

# Add a post to the database.
def add_post_to_db(cursor, data):
  query = "INSERT INTO posts (url) VALUES (%s)"
  cursor.execute(query, (data["url"],))
  cursor.connection.commit()

# Create a Tumblr post.
def post_to_tumblr(tpy, data, options):
  if options["post_nsfw"] or not data["over_18"]:
    title = html.parser.HTMLParser().unescape(data["title"])
    url = to_direct_link(data["url"])

    blog_url = options["blog_url"]
    all_tags = options["default_tags"] + "," + \
               data["subreddit"] + "," + \
               ("nsfw" if data["over_18"] else "")

    post_type = get_post_type(url)
    params = get_post_params(post_type, all_tags, url, title, \
                             "reddit.com" + data["permalink"])

    log(params)

    try:
      post = tpy.post("post", blog_url = blog_url, params = params)
      return True
    except TumblpyError as e:
      log("TumblpyError: {0} Photo URL: {1}".format(e, url))
      return False

# Turn imgur.com links into direct image links.
def to_direct_link(url):
  p = urlparse(url)
  if ".gifv" in p.path:
    # return urlunparse([p.scheme, p.netloc, p.path[:-1], "", "", ""])
    # TODO: changing .gifv extension to .gif does not let tumblr upload it.
    return url
  elif p.netloc == "imgur.com" and "gallery" not in p.path and "a/" not in p.path:
    return urlunparse([p.scheme, "i.imgur.com", p.path + ".gif", "", "", ""])
  else:
    return url

# Returns the type of post to create for a given URL.
def get_post_type(url):
  if url[(url.rfind(".") + 1):] in ["gif", "jpeg", "jpg", "png"]:
    return "photo"
  elif urlparse(url).netloc in ("youtube.com", "youtu.be"):
    return "video"
  else:
    return "link"

# Get the parameters for a Tumblr post in the form of a dictionary.
def get_post_params(post_type, tags, url, title, permalink):
  default_params = {"state": "published", "tags": tags}
  extra_params = {"photo": {"caption": title, "source": url, "link": permalink},
                  "video": {"caption": title, "embed": url},
                  "link": {"title": title, "url": url}}
  params_with_post_type = dict(default_params, type = post_type)
  return dict(params_with_post_type, **extra_params[post_type])

main()
cleanup()
