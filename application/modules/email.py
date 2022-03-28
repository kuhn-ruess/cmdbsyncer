# Version 1.1
from threading import Thread
from flask import current_app, render_template
from flask_mail import Message
from application import mail


def send_async_email(app, msg):
    with app.app_context():
        mail.send(msg)


def send_email(to, subject, template, **kwargs):
    try:
        app = current_app._get_current_object()
    except:
        app = kwargs['ext_app']
    send_email_inner(to, subject, template, app, **kwargs)

def send_email_inner(to, subject, template, app, **kwargs):
    with app.app_context():

        if 'SENDER' in kwargs:
            sender = kwargs['SENDER']
        else:
            sender = app.config['MAIL_SENDER']

        msg = Message(
            app.config['MAIL_SUBJECT_PREFIX'] + ' ' + subject,
            sender=sender,
            recipients=[to]
        )
        # msg.body = render_template(template + '.txt', **kwargs)
        msg.html = render_template(template + '.html', **kwargs)
        if 'attachment_file' in kwargs:
            msg.attach(
                kwargs['attachment_name'],
                kwargs['attachment_mime'],
                kwargs['attachment_file']
            )

        if 'attachment_path' in kwargs:
            with app.open_resource(kwargs['attachment_path']) as attachment:
                msg.attach(
                    kwargs['attachment_name'],
                    kwargs['attachment_mime'],
                    attachment.read()
                )

        thr = Thread(target=send_async_email, args=[app, msg])
        thr.start()
        return thr
