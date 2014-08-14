"""
Substitutes a file with query parameters. These can come from environment
variables or from an (optional) XML file.

Queries are a bit like XPath::

    /elem/elem ...

An implicit ``::text()`` is appended so you get all the text in the specified
element.
"""

import muddled.utils as utils
import re

import logging
def log(*args, **kwargs):
    args = [str(arg) for arg in args]
    logging.getLogger(__name__).warning(' '.join(args))

g_trace_parser = False

def get_text_in_xml_node(node):
    """
    Given an XML node, collect all the text in it.
    """
    elems = [ ]
    for n in node.childNodes:
        if (n.nodeType == n.TEXT_NODE):
            elems.append(n.data)

    result = "".join(elems)
    # Strip trailing '\n's
    if (result[:-1] == '\n'):
        result = result[:-1]

    return result

def query_result(keys, doc_node):
    """
    Given a list of keys and a document node, return the XML node
    which matches the query, or None if there isn't one.
    """
    result = doc_node

    for i in keys:
        next_result = None

        for j in result.childNodes:
            if (j.nodeType == j.ELEMENT_NODE and \
                    (j.nodeName == i)):
                next_result = j
                break

        if (next_result is None):
            return None
        else:
            result = next_result

    return result

def split_query(query):
    """
    Split a query into a series of keys suitable to be passed to query_result().
    """

    result = query.split("/")
    if (result[0] == ''):
        # Absolute path - lop off the initial empty string
        result = result[1:]

    return result

def query_string_value(xml_doc, env, k):
    """
    Given a string-valued query, work out what the result was
    """
    v = None
    result_node = None

    if (len(k) == 0):
        return ""

    if (k[0] == '/'):
        # An XML query
        if xml_doc is not None:
            result_node = query_result(split_query(k), xml_doc)
        if (result_node is not None):
            v = get_text_in_xml_node(result_node)
    else:
        # An environment variable
        if (k in env):
            v = env[k]
        else:
            raise utils.GiveUp("Environment variable '%s' not defined."%k)

    return v

class PushbackInputStream(object):
    """
    A pushback input stream based on a string. Used in our recursive descent
    parser
    """

    def __init__(self, str):
        self.input = str
        self.idx = 0
        self.pushback_char = -1
        self.line_no = 0
        self.char_no = 0
        self.newline_starting = True    # on the next char read

    def next(self):
        res = -1
        if self.pushback_char != -1:
            res = self.pushback_char
            self.pushback_char = -1
            if g_trace_parser:
                log("next(%d,%d) = %c (pushback)"%(self.line_no, self.char_no, res))
            # We don't want to change our line or character number
            return res
        elif self.idx >= len(self.input):
            res = -1
        else:
            res = self.input[self.idx]
            self.idx += 1

        if self.newline_starting:       # we are starting a new line now
            self.char_no = 0
            self.line_no += 1
            self.newline_starting = False

        if res != -1:
            self.char_no += 1

        if res == '\n':
            self.newline_starting = True    # on the next char read

        if g_trace_parser:
            if res < 0:
                log("next(%d,%d) = -1"%(self.line_no, self.char_no))
            else:
                log("next(%d,%d) = %c "%(self.line_no, self.char_no, res))

        return res

    def push_back(self,c):
        # Only a single push back is allowed, but we don't actually check
        self.pushback_char = c

    def peek(self):
        if (self.pushback_char != -1):
            return self.pushback_char
        elif (self.idx >= len(self.input)):
            return -1
        else:
            return self.input[self.idx]

    def report(self):
        return "line %d, char %d"%(self.line_no, self.char_no)

    def print_what_we_just_read(self):
        lines = self.input.splitlines()
        maxlen = len('%d'%self.line_no)
        log('Just read:')
        count = self.line_no - 2
        for line in lines[self.line_no-3:self.line_no]:
            log('Line %*d: %s'%(maxlen, count, line))
            count += 1
        if self.idx == len(self.input):
            log('     %s  <EOF>'%(' '*maxlen))

    def get_line(self, line_no):
        """Return line 'line_no'. Line numbers start at 1.
        """
        lines = self.input.splitlines()
        return lines[line_no - 1]



class TreeNode(object):
    """
    A TreeNode contains itself, followed by all its children, so this is
    essentially a left tree.
    """

    StringType = "string"
    InstructionType = "instruction"
    ContainerType = "container"


    def __init__(self, in_type, input_stream):
        self.type = in_type
        self.children = [ ]
        self.string = ""
        # The default function is to evaluate something.
        self.instr_type = "val"
        self.function = ""
        # We keep a note of the input stream for error messages
        self.input_stream = input_stream


    def set_string(self, inStr):
        self.type = TreeNode.StringType
        self.string = inStr

    def append_child(self, n):
        self.children.append(n)

    def set_val(self, v):
        """
        v is the value which should be evaluated to get the
        value to evaluate.
        """
        self.instr_type = "val"
        self.function = ""
        self.expr = v

    def set_fn(self, fn_name, params, rest):
        """
        fn_name is the name of the function
        params and rest are lists of nodes
        """
        self.instr_type = "fn"
        self.function = fn_name
        self.params = params
        self.append_child(rest)

    def __str__(self):
        buf = [ ]
        if (self.type == TreeNode.StringType):
            buf.append("{ String: '%s' "%(self.string))
        elif (self.type == TreeNode.InstructionType):
            if (self.instr_type == "val"):
                buf.append("{ ValInstr: !%s!  "%(self.expr))
            elif (self.instr_type == "fn"):
                param_str = [ "[ " ]
                for p in self.params:
                    param_str.append("%s "%p)
                param_str.append(" ]")


                buf.append("{ FnInstr: %s Params: [ %s ] "%(self.function,
                                                            "".join(param_str)))
            else:
                buf.append("{ UnknownInstr type = %s "%(self.instr_type))
        elif (self.type == TreeNode.ContainerType):
            buf.append("{ Container ")
        buf.append("\n")
        for c in self.children:
            buf.append(" - %s \n"%c)
        buf.append("}\n")
        return "".join(buf)

    def append_children(self, xml_doc, env, output_list):
        for c in self.children:
            c.eval(xml_doc, env, output_list)

    def eval(self, xml_doc, env, output_list):
        """
        Evaluate this node with respect to xml_doc, env and place your
        output in output_list - a list of strings.
        """
        if (self.type == TreeNode.StringType):
            # Easy enough ..
            output_list.append(self.string)
            for c in self.children:
                c.eval(xml_doc, env, output_list)
        elif (self.type == TreeNode.ContainerType):
            for c in self.children:
                c.eval(xml_doc, env, output_list)
        elif (self.type == TreeNode.InstructionType):
            # Evaluate some sort of function.
            if (g_trace_parser):
                log("Eval instr: %s"%(self.instr_type))

            if (self.instr_type == "val"):
                self.val(xml_doc, env, output_list)
            elif (self.instr_type == "fn"):
                if (self.function == "val"):
                    self.fnval(xml_doc, env, output_list)
                elif (self.function == "ifeq"):
                    self.ifeq(xml_doc, env, output_list, True)
                elif (self.function == "ifneq"):
                    self.ifeq(xml_doc,env,output_list, False)
                elif (self.function == "echo"):
                    self.echo(xml_doc, env, output_list)
            else:
                # Evaluates to nothing.
                pass

    def eval_str(self, xml_doc, env):
        """
        Evaluate this node and return the result as a string
        """
        output_list = [ ]
        self.eval(xml_doc, env, output_list)
        return "".join(output_list)

    def val(self, xml_doc, env, output_list):
        key_name = self.expr.eval_str(xml_doc, env)
        key_name = key_name.strip()


        if (key_name is None):
            res =  ""
        else:
            res = query_string_value(xml_doc, env, key_name)

        if (res is None):
            raise utils.GiveUp("Attempt to substitute key '%s' which does not exist."%key_name)

        if (g_trace_parser):
            log("node.val(%s -> %s) = %s"%(self.expr, key_name, res))

        output_list.append(res)


    def fnval(self, xml_doc, env, output_list):
        if (len(self.params) != 1):
            raise utils.GiveUp("val() must have exactly one parameter")

        key_name = self.params[0].eval_str(xml_doc, env)
        key_name = key_name.strip()


        if (key_name is None):
            res =  ""
        else:
            res = query_string_value(xml_doc, env, key_name)

        if (res is None):
            raise utils.GiveUp("Attempt to substitute key '%s' which does not exist."%key_name)

        if (g_trace_parser):
            log("node.fnval(%s -> %s) = %s"%(self.params[0], key_name, res))

        output_list.append(res)

    def ifeq(self, xml_doc, env, output_list, polarity):
        # Must have two parameters ..
        if (len(self.params) != 2):
            raise utils.GiveUp("ifeq() must have two parameters")

        key = self.params[0].eval_str(xml_doc, env)
        key = key.strip()
        value = self.params[1].eval_str(xml_doc, env)

        key_value = query_string_value(xml_doc, env, key)
        if (key_value is not None):
            key_value = key_value.strip()

        if (polarity):
            if (key_value == value):
                self.append_children(xml_doc, env, output_list)
        else:
            if (key_value != value):
                self.append_children(xml_doc, env, output_list)

    def echo(self, xml_doc, env, output_list):
        # Just echo your parameters.
        for p in self.params:
            p.eval(xml_doc, env, output_list)

def parse_document(input_stream, node, end_chars, has_escapes):
    """
    Parse a document into a tree node.
    Ends with end_char (which may be -1)

    Leaves the input stream positioned at end_char.
    """

    # States:
    #
    #   0 - Parsing text.
    #   1 - Got '$'.
    #   2 - Got '$$'
    #   3 - Got '\'
    state = 0
    cur_str = []
    start_line_no = input_stream.line_no
    start_char_no = input_stream.char_no - 1 # because we already ate 1 char

    state_desc = {0:'Parsing text',
                  1:'After $',
                  2:'After $$',
                  3:'After \\'}

    while True:
        c = input_stream.next()

        if (g_trace_parser):
            log("parse_document(): c = %s cur_str = [ %s ] state = %d"%(c,",".join(cur_str), state))

        ends_now = (c < 0)
        if ((not ends_now) and  state == 0 and end_chars is not None):
            ends_now = (c in end_chars)

        if ((end_chars is not None) and (c < 0)):
            #input_stream.print_what_we_just_read()
            log('Current state is %s'%state_desc[state])
            end_chars = ', '.join(map(repr, end_chars))
            log("Expected end char (%s) for item at line %d, char %d"%(
                    end_chars,
                    start_line_no,
                    start_char_no))
            log('  %s'%input_stream.get_line(start_line_no))
            log('  %s^ char %d'%(' '*(start_char_no - 1), start_char_no))
            log("The text that was not ended is %r"%(''.join(cur_str)))
            raise utils.GiveUp("Syntax Error: Input text ends whilst waiting for"
                               " end char (%s)"%end_chars)

        if (ends_now):
            cur_node = TreeNode(TreeNode.StringType, input_stream)
            cur_node.set_string("".join(cur_str))
            node.append_child(cur_node)
            # Push back ..
            input_stream.push_back(c)
            cur_str = [ ]
            if (g_trace_parser):
                log("parse_document(): terminating character %r detected. Ending."%(c))
            return

        if (state == 0):
            if (c == '$'):
                state = 1
            elif (c== '\\' and has_escapes):
                # Literal.
                state = 3
            else:
                cur_str.append(c)
        elif (state == 1):
            if (c == '$'):
                # Got '$$'
                state = 2
            elif (c == '{'):
                # Start of an instruction.
                cur_node = TreeNode(TreeNode.StringType, input_stream)
                cur_node.set_string("".join(cur_str))
                cur_str = [ ]
                node.append_child(cur_node)
                parse_instruction(input_stream, node)
                # Eat the trailing character
                x = input_stream.next()
                if x != '}':
                    log('  %s'%input_stream.get_line(start_line_no))
                    log('  %s^ char %d'%(' '*(start_char_no - 1), start_char_no))
                    log("The text that was not ended is %r"%(''.join(cur_str)))
                    raise utils.GiveUp('Instruction did not end with %r: %s'%('}', input_stream.report()))
                # .. and back to the start.
                state = 0
            else:
                cur_str.append('$')
                cur_str.append(c)
                state = 0
        elif (state == 2):
            if (c == '{'):
                # Ah. Literal ${
                cur_str.append('$')
                cur_str.append('{')
            else:
                # Literal $$<c>
                cur_str.append('$')
                cur_str.append('$')
                cur_str.append(c)
            state = 0
        elif (state == 3):
            # Unescape.
            cur_str.append(c)
            state = 0


def skip_whitespace(in_stream):
    """
    Skip some whitespace
    """
    while True:
        c = in_stream.peek()
        if (c == ' ' or c=='\r' or c=='\t' or c=='\n'):
            in_stream.next()
        else:
            return

def flatten_literal_node(in_node):
    """
    Flatten a literal node into a string. Raise GiveUp if we, um, fail.
    """
    lst = [ ]

    if (in_node.type == TreeNode.StringType):
        lst.append(in_node.string)
    elif (in_node.type == TreeNode.ContainerType):
        pass
    else:
        # Annoyingly, we can't report here yet.          XXX Pardon?
        in_node.input_stream.print_what_we_just_read() # XXX Is this useful?
        raise utils.GiveUp("Non literal where literal expected.")

    for i in in_node.children:
        lst.append(flatten_literal_node(i))

    if (g_trace_parser):
        log("Flatten: %s  Gives '%s'\n"%(in_node, "".join(lst)))

    return "".join(lst)

def parse_literal(input_stream, echars):
    """
    Given a set of end chars, parse a literal.
    """
    dummy = TreeNode(TreeNode.ContainerType, input_stream)
    parse_document(input_stream, dummy, echars, True)
    return flatten_literal_node(dummy)


def parse_param(input_stream, node, echars):
    """
    Parse a parameter: may be quoted (in which case ends at ") else ends at echars
    """
    skip_whitespace(input_stream)

    if input_stream.peek() == '"':
        input_stream.next(); # Skip the quote.
        closing_quote = set([ '"' ])
        parse_document(input_stream, node, closing_quote, True)
        # Skip the '"'
        c = input_stream.peek()
        if c != '"':
            raise utils.GiveUp('Quoted parameter did not end with %r: %s'%('"', input_stream.report()))
        input_stream.next()
        skip_whitespace(input_stream)
        c = input_stream.peek()
        if (c in echars):
            # Fine.
            return
        else:
            input_stream.print_what_we_just_read()
            raise utils.GiveUp("Quoted parameter ends with invalid character %r: "
                               "%s"%(c, input_stream.report()))
    else:
        parse_document(input_stream, node, echars, True)

def parse_instruction(input_stream, node):

    """
    An instruction ends at }, and contains:

    fn:<name>(<args>, .. ) rest}

    or

    <stuff>}
    """

    if (g_trace_parser):
        log("parse_instruction() begins: ")

    skip_whitespace(input_stream)

    # This is an instruction node, so ..
    if (input_stream.peek() == '"'):
        if (g_trace_parser):
            log("parse_instruction(): quoted literal detected")

        # Consume that last peek'd character...
        input_stream.next()
        skip_whitespace(input_stream)
        # Quoted string. So we know ..
        result = TreeNode(TreeNode.InstructionType, input_stream)
        container = TreeNode(TreeNode.ContainerType, input_stream)
        echars = set([ '"' ])
        old_report = input_stream.report() # In case we need it later..
        parse_document(input_stream, container, echars, True)
        if (input_stream.next() != '"'):
            input_stream.print_what_we_just_read()
            raise utils.GiveUp("Literal instruction @ %s never ends"%(old_report))

        skip_whitespace(input_stream)
        c = input_stream.next()
        if (c != '}'):
            # Rats
            input_stream.print_what_we_just_read()
            raise utils.GiveUp("Syntax Error - no end to literal instruction @ %s"%
                                (input_stream.report()))
        # Remember to push back the '}' for our caller to find
        input_stream.push_back(c)
        # Otherwise ..
        result.set_val(container)
        node.append_child(result)
        if (g_trace_parser):
            log("parse_instruction(): ends")

        return

    # Otherwise ..
    dummy = TreeNode(TreeNode.ContainerType, input_stream)
    result = TreeNode(TreeNode.InstructionType, input_stream)

    echars = set([ ':', '}' ])
    parse_document(input_stream, dummy, echars, True)
    c = input_stream.next()
    if (c == ':'):
        # Must have been a literal.
        str = flatten_literal_node(dummy)

        # A directive of some kind.
        if (str == "fn"):
            # Gotcha! Function must also be a literal.
            echars = set([ '(', '}' ])
            fn_name = parse_literal(input_stream, echars)
            params = [ ]
            rest = TreeNode(TreeNode.ContainerType, input_stream)
            c2 = input_stream.next()
            if (c2 == '('):
                # We have parameters!
                while True:
                    echars = set([ ',', ')' ] )
                    param_node = TreeNode(TreeNode.ContainerType, input_stream)
                    parse_param(input_stream, param_node, echars)
                    params.append(param_node)
                    c = input_stream.next()
                    if (c != ','):
                        break
            # End of params.
            echars = set(['}'])
            parse_document(input_stream, rest, echars, True)
            result.set_fn(fn_name, params, rest)
        else:
            input_stream.print_what_we_just_read()
            raise utils.GiveUp("Invalid designator in value: %r at %s"%(str, input_stream.report()))
    else:
        # This was the end of the directive.
        result.set_val(dummy)
        # .. BUT! We haven't pushed '}' back so ..
        input_stream.push_back(c)


    # In many ways, it is worth adding our result to the parse tree.
    if (g_trace_parser):
        log("parse_instruction(): ends (2)")
    node.append_child(result)

def subst_str(in_str, xml_doc, env):
    """
    Substitute ``${...}`` in in_str with the appropriate objects - if XML
    doesn't match, try an environment variable.

    Unescape ``$${...}`` in case someone actually wanted `${...}`` in the
    output.

    Functions can be called with:
    ${fn:NAME(ARGS) REST}

    name can be: ifeq(query,value) - in which case REST is substituted.
                 val(query)  - just looks up query.

    """

    stream = PushbackInputStream(in_str)
    top_node = TreeNode(TreeNode.ContainerType, stream)
    parse_document(stream, top_node, None, False)

    output_list = []
    top_node.eval(xml_doc, env, output_list)

    return "".join(output_list)

def subst_file(in_file, out_file, xml_doc, env):

    f_in = open(in_file, "r")
    f_out = open(out_file, "w")

    contents = f_in.read()
    out = subst_str(contents, xml_doc, env)
    f_out.write(out)

#    lines = ""
#    while True:
#        in_line = f_in.readline()
#        if (in_line == ""):
#            break
#
#        out_line = subst_str(in_line, xml_doc, env)
#        f_out.write(out_line)




# End File.


