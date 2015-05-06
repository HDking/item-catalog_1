from flask import Flask, render_template, url_for, request, redirect, flash, jsonify
app = Flask(__name__)

#SQL alchemy imports
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from project3_database_setup import Base, Category, Item

#new for authentication and authorization steps
from flask import session as login_session
import random, string
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

CLIENT_ID= json.loads(
	open('client_secrets.json', 'r').read())['web']['client_id']

#link with the database
engine = create_engine('sqlite:///catalog.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


#API endpoints

#/catalog/JSON/
@app.route('/catalog/JSON/')
def catalogJSON():
	categories = session.query(Category).all()
	return jsonify(Category=[category.serialize for category in categories])

#/catalog/restaurant_id/items/JSON
@app.route('/catalog/<int:category_id>/JSON/')
def itemsJSON(category_id):
	category = session.query(Category).filter_by(id=category_id).one()
	items = session.query(Item).filter_by(category_id=category.id).all()
	return jsonify(Item=[item.serialize for item in items])

#/catalog/restaurant_id/item_id/JSON
@app.route('/catalog/<int:category_id>/<int:item_id>/JSON/')
def oneItemJSON(category_id, item_id):
	category = session.query(Category).filter_by(id=category_id).one()
	item = session.query(Item).filter_by(id=item_id).one()
	return jsonify(Item= item.serialize)

#Create a state token to prevent request
#Store it in the session for later validation
@app.route('/login/')
def showLogin():
  state = ''.join(random.choice(string.ascii_uppercase + string.digits) for x in xrange(32))
  login_session['state'] = state
  return render_template('login.html', STATE = state)

@app.route('/gconnect', methods=['POST'])
def gconnect():
	if request.args.get('state') != login_session['state']:
		response = make_response(json.dumps('Invalid state parameter'), 401)
		response.headers['Content-Type'] = 'application/json'
		return response
	code = request.data

	try: 
		#Upgrade the authorization code into a credentials object
		oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
		oauth_flow.redirect_uri = 'postmessage'
		credentials = oauth_flow.step2_exchange(code)
	except FlowExchangeError: 
		response = make_response(json.dumps('Failed to upgrade the authorization code.'), 401)
		resonse.headers['Content-Type'] = 'application/json'
		return response
	#check that the access token is valid. 
	access_token = credentials.access_token
	url=('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s' % access_token)
	h = httplib2.Http()
	result = json.loads(h.request(url, 'GET')[1])
	#If there was an error in the access token info, abort.
	if result.get('error') is not None: 
		response = make_response(json.dumps(result.get('error')), 50)
		response.headers['Content-Type'] = 'application/json'
	#Verify that the acess token is used for the intended user.
	gplus_id = credentials.id_token['sub']
	if result['user_id'] != gplus_id:
		response = make_response(
			json.dumps("Token's user ID doesn't match given user ID."), 401)
		response.headers['Content-Type'] = 'application/json'
		return response
	#Verify that the access token is valid for this app. 
	if result['issued_to'] != CLIENT_ID:
		response = make_response(
			json.dumps("Token's client ID doesn't match app's."), 401)
		response.headers['Content-Type'] = 'application/json'
		return response
	#Check to see if user is already logged in
	stored_credentials = login_session.get('credentials')
	stored_gplus_id = login_session.get('gplus_id')
	if stored_credentials is not None and gplus_id == stored_gplus_id:
		response = make_response(json.dumps('Current user is already connected.'), 200)
		response.headers['Content-Type'] = 'application/json'

	#Store the access token in the session for later use. 
	login_session['credentials'] = credentials.to_json()
	login_session['gplus_id'] = gplus_id

	#Get user info
	userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
	params = {'access_token' : credentials.access_token, 'alt':'json'}
	answer = requests.get(userinfo_url, params=params)
	data = json.loads(answer.text)

	login_session['username'] = data["name"]
	login_session['picture'] = data["picture"]
	login_session['email'] = data["email"]

	output = ''
	output += '<h1>Welcome, '
	output += login_session['username']

	output += '!</h1>'
	output += '<img src='' '
	output += login_session['picture']
	output += ' " style = " width: 300px; height: 300px; border-radius: 150px; -webkit-border-radius: 150px; -moz-border-radius: 150px;"> '

	flash("you are now logged in as %s" %login_session['username'])
	return output

 	#DISCONNECT - Revoke a current user's doken and reset their login_session. 
@app.route("/gdisconnect")
def gdisconnect():
	#Only disconnect a connected user.
	credentials = login_session.get('credentials')
	if credentials is None:
		response = make_response(json.dumps('Current user not connected.'),401)
		response.headers['Content-Type'] = 'application/json'
		return response
	#Execute HTTP GET request to revoke current token
	access_token = credentials.access_token
	url = 'https://accounts.google.com/o/oauth2/revoke?/token=%s' %access_token
	h = httplib2.Http()
	result = h.request(url, 'GET')[0]

	if result['status'] == '200':
		#Reset the user's session.
		del login_session['credentials']
		del login_session['gplus_id']
		del login_session['username']
		del login_session['email']
		del login_session['picture']

		response = make_response(json.dumps('disconnected.'),200)
		response.headers['Content-Type'] = 'application/json'
		return response
	else: 
		# For whatever reason, the given token was invalid
		response = make_response(json.dumps('Failed to revoke token for given user,'), 400)
		response.headers['Content-Type'] = 'application/json'
		return response


#Routes to the pages
#route to the catalog page which shows categories and the latest items
@app.route('/')
@app.route('/catalog/')
def showCategories():
	categories = session.query(Category).all()
	#nog niet helemaal, maar het moet aflopend zijn gebaseerd op de laatste ids
	latestItems = session.query(Item).all()
	return render_template('catalog.html', categories = categories, items = latestItems)

#route to add a category
@app.route('/catalog/new/', methods=['GET','POST'])
def newCategory():
	if 'username' not in login_session:
		return redirect('/login')
	if request.method == 'POST':
		newCategory = Category(name=request.form['name'])
		session.add(newCategory)
		session.commit()
		return redirect(url_for('showCategories'))
	else:
		return render_template('newCategory.html')

#route to delete a category
@app.route('/catalog/<int:category_id>/delete/', methods=['GET', 'POST'])
def deleteCategory(category_id):
	deleteCat = session.query(Category).filter_by(id=category_id).one()
	if 'username' not in login_session:
		return redirect('/login')
	if request.method == 'POST':
		session.delete(deleteCat)
		session.commit()
		return redirect(url_for('showCategories'))
	else:
		return render_template('deleteCategory.html', category = deleteCat)

#route to edit a category name
@app.route('/catalog/<int:category_id>/edit/', methods=['GET','POST'])
def editCategory(category_id):
	category = session.query(Category).filter_by(id=category_id).one()
	if 'username' not in login_session:
		return redirect('/login')
	if request.method =='POST':
		if request.form['name']:
			category.name = request.form['name']
		session.add(category)
		session.commit()
		return redirect(url_for('showCategories'))
	else:
		return render_template('editCategory.html', category = category)

#route to the category page which shows its items
@app.route('/catalog/<int:category_id>/')
def showItems(category_id):
	categories = session.query(Category).all()
	category = session.query(Category).filter_by(id = category_id).one()
	items = session.query(Item).filter_by(category_id = category_id).all()
	return render_template('items.html', categories=categories, category=category, items = items)

#route to create a new item
@app.route('/catalog/<int:category_id>/new/', methods=['GET', 'POST'])
def newItem(category_id):
	category = session.query(Category).filter_by(id=category_id).one()
	if 'username' not in login_session:
		return redirect('/login')
	if request.method=='POST':
		newItem = Item(name=request.form['name'], description=request.form['description'], category_id=category.id)
		session.add(newItem)
		session.commit()
		return redirect(url_for('showItems', category_id=category.id))
	else:
		return render_template('newItem.html',category_id=category.id, category=category)

#route to the description of a item
@app.route('/catalog/<int:category_id>/<int:item_id>/')
def showDescription(category_id, item_id):
	category = session.query(Category).filter_by(id=category_id).one()
	item = session.query(Item).filter_by(id=item_id).one()
	return render_template('description.html',item_id=item.id, item = item, category=category)

#route to delete an item
@app.route('/catalog/<int:category_id>/<int:item_id>/delete/', methods=['GET', 'POST'])
def deleteItem(category_id, item_id):
	category = session.query(Category).filter_by(id=category_id).one()
	item = session.query(Item).filter_by(id=item_id).one()
	if 'username' not in login_session:
		return redirect('/login')
	if request.method=='POST':
		session.delete(item)
		session.commit()
		return redirect(url_for('showItems', category_id=category.id))
	else:
		return render_template('deleteItem.html', category= category, item=item)

#route to edit an item 
# Moet nog een tweede invoer waarde krijgen, de description en wellicht de category
@app.route('/catalog/<int:category_id>/<int:item_id>/edit/', methods=['GET', 'POST'])
def editItem(category_id, item_id):
	category = session.query(Category).filter_by(id=category_id).one()
	item= session.query(Item).filter_by(id=item_id).one()
	if 'username' not in login_session:
		return redirect('/login')
	if request.method=='POST':
		if request.form['name']:
			item.name = request.form['name']
		session.add(item)
		session.commit()
		return redirect(url_for('showDescription', item_id=item.id, item=item, category_id=category.id))
	else:
		return render_template('editItem.html', item=item, category_id=category.id, item_id=item.id, category=category)


if __name__ == '__main__':
	app.secret_key = 'super secret key'
	app.debug=True
	app.run(host='0.0.0.0', port=5000)